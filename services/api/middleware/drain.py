"""
Drain middleware for graceful shutdown.

Responsibilities:
- Track in-flight request count via an atomic counter.
- When draining (accepting=False), return 503 for new requests.
- Allow health-check endpoints through even during drain.
- Provide wait_for_drain(timeout_s) so the shutdown sequence can
  block until all in-flight requests have completed.

Does NOT:
- Trigger shutdown or decide when to drain — that is the lifespan's job.
- Disconnect broker adapters or close DB connections.
- Modify request/response bodies.

Dependencies:
- threading: for Lock-based atomic counter.
- starlette: BaseHTTPMiddleware for ASGI integration.
- structlog: structured logging.

Error conditions:
- None raised. 503 is returned as a normal HTTP response.

Example:
    drain = DrainMiddleware()
    app.add_middleware(type(drain), drain_state=drain)

    # During shutdown:
    drain.stop_accepting()
    remaining = drain.wait_for_drain(timeout_s=30.0)
    if remaining > 0:
        logger.warning("drain.timeout", remaining=remaining)
"""

from __future__ import annotations

import threading
import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

# Paths that are always allowed, even during drain.
# Health probes must succeed for load balancer readiness.
_EXEMPT_PATHS: frozenset[str] = frozenset({"/health", "/health/"})


class _AtomicCounter:
    """
    Thread-safe integer counter.

    Uses a threading.Lock to protect increments, decrements, and reads.
    Always non-negative — decrement below 0 is clamped.

    Responsibilities:
    - Provide atomic increment/decrement/read operations.
    - Guarantee non-negative count.

    Does NOT:
    - Implement any business logic.
    """

    def __init__(self) -> None:
        """Initialize the counter at zero with a threading lock."""
        self._value: int = 0
        self._lock = threading.Lock()

    def increment(self) -> int:
        """
        Atomically increment and return the new value.

        Returns:
            The count after incrementing.
        """
        with self._lock:
            self._value += 1
            return self._value

    def decrement(self) -> int:
        """
        Atomically decrement and return the new value.

        Clamps at 0 to prevent negative counts from unbalanced calls.

        Returns:
            The count after decrementing (>= 0).
        """
        with self._lock:
            self._value = max(0, self._value - 1)
            return self._value

    @property
    def value(self) -> int:
        """
        Read the current count.

        Returns:
            The current counter value.
        """
        with self._lock:
            return self._value


class DrainMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that supports graceful request draining during shutdown.

    In normal operation, all requests pass through with an in-flight
    counter tracking active requests. When stop_accepting() is called
    (typically at the start of shutdown), new requests receive a 503
    response while in-flight requests are allowed to complete.

    The shutdown sequence calls wait_for_drain(timeout_s) to block
    until all in-flight requests finish or the timeout expires.

    Responsibilities:
    - Track in-flight requests via atomic counter.
    - Reject new requests with 503 during drain.
    - Exempt health-check paths from drain (load balancer probes).
    - Provide blocking wait for all in-flight requests to complete.

    Does NOT:
    - Trigger or control the shutdown sequence.
    - Close connections, adapters, or database pools.

    Dependencies:
    - _AtomicCounter for thread-safe in-flight tracking.
    - structlog for structured logging.

    Example:
        drain = DrainMiddleware()
        app.add_middleware(type(drain), drain_state=drain)
        # Shutdown:
        drain.stop_accepting()
        remaining = drain.wait_for_drain(timeout_s=30.0)
    """

    def __init__(
        self, app: object | None = None, *, drain_state: DrainMiddleware | None = None
    ) -> None:
        """
        Initialize the drain middleware.

        When used as a shared state object (passed via drain_state), the
        middleware delegates to the shared object's counter and accepting
        flag. When used standalone (no drain_state), it manages its own.

        Args:
            app: The ASGI application (passed by Starlette's add_middleware).
            drain_state: Optional shared DrainMiddleware instance whose
                state (counter, accepting flag) this middleware should use.
        """
        self._in_flight: _AtomicCounter
        self._accepting: bool
        self._accepting_lock: threading.Lock

        if drain_state is not None:
            # Share state from the provided drain instance
            self._in_flight = drain_state._in_flight
            self._accepting = drain_state._accepting
            self._accepting_lock = drain_state._accepting_lock
        else:
            self._in_flight = _AtomicCounter()
            self._accepting = True
            self._accepting_lock = threading.Lock()

        if app is not None:
            super().__init__(app)  # type: ignore[arg-type]  # Starlette BaseHTTPMiddleware expects ASGI callable; we pass the app object as-is

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def in_flight_count(self) -> int:
        """
        Current number of in-flight requests.

        Returns:
            Non-negative integer count of requests being processed.
        """
        return self._in_flight.value

    @property
    def is_accepting(self) -> bool:
        """
        Whether the middleware is accepting new requests.

        Returns:
            True if new requests are allowed; False during drain.
        """
        with self._accepting_lock:
            return self._accepting

    def stop_accepting(self) -> None:
        """
        Stop accepting new requests — begin draining.

        After this call, new requests (except health probes) receive
        a 503 Service Unavailable response. In-flight requests already
        past the middleware continue processing normally.
        """
        with self._accepting_lock:
            self._accepting = False
        logger.info(
            "drain.stop_accepting",
            in_flight=self._in_flight.value,
            component="drain_middleware",
        )

    def resume_accepting(self) -> None:
        """
        Resume accepting new requests.

        Used for testing or if shutdown is cancelled.
        """
        with self._accepting_lock:
            self._accepting = True
        logger.info(
            "drain.resume_accepting",
            component="drain_middleware",
        )

    def wait_for_drain(self, timeout_s: float = 30.0) -> int:
        """
        Block until all in-flight requests complete or timeout expires.

        Polls the in-flight counter every 0.1 seconds. Returns 0 if
        all requests completed, or the remaining count on timeout.

        Args:
            timeout_s: Maximum seconds to wait. Default 30.

        Returns:
            Number of remaining in-flight requests (0 = fully drained).

        Example:
            remaining = drain.wait_for_drain(timeout_s=30.0)
            if remaining > 0:
                logger.warning("drain.timeout", remaining=remaining)
        """
        deadline = time.monotonic() + timeout_s
        poll_interval = 0.1

        while time.monotonic() < deadline:
            current = self._in_flight.value
            if current == 0:
                logger.info(
                    "drain.complete",
                    component="drain_middleware",
                )
                return 0
            time.sleep(poll_interval)

        remaining = self._in_flight.value
        if remaining > 0:
            logger.warning(
                "drain.timeout",
                remaining=remaining,
                timeout_s=timeout_s,
                component="drain_middleware",
            )
        return remaining

    # ------------------------------------------------------------------
    # Middleware dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next: object) -> Response:
        """
        Process an incoming request through the drain middleware.

        If draining and the path is not exempt, returns 503 immediately.
        Otherwise, increments the in-flight counter, processes the request,
        and decrements on completion (even on exceptions).

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The response from downstream, or a 503 JSONResponse if draining.
        """
        path = request.url.path.rstrip("/") or "/"
        exempt = path in _EXEMPT_PATHS or path.rstrip("/") in _EXEMPT_PATHS

        if not self.is_accepting and not exempt:
            logger.debug(
                "drain.rejected",
                path=path,
                method=request.method,
                component="drain_middleware",
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "Service is shutting down. Please retry later."},
                headers={"Retry-After": "5"},
            )

        self._in_flight.increment()
        try:
            response = await call_next(request)  # type: ignore[operator]
            return response
        finally:
            self._in_flight.decrement()
