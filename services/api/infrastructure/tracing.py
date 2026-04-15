"""
OpenTelemetry distributed tracing setup for FXLab API.

Purpose:
    Configure OpenTelemetry SDK for distributed tracing across the FXLab
    execution layer. Traces connect HTTP requests to service calls to broker
    adapter operations, providing end-to-end visibility.

Responsibilities:
    - Initialize the TracerProvider with configurable OTLP exporter.
    - Auto-instrument FastAPI, SQLAlchemy, and httpx.
    - Provide manual span helpers for broker adapter and safety operations.
    - Propagate correlation ID as trace baggage for log-trace linking.
    - Gracefully degrade when OTEL endpoint is not configured (opt-in).

Does NOT:
    - Contain business logic.
    - Manage Jaeger/Tempo infrastructure (see docker-compose).
    - Replace structured logging (traces complement logs, not replace them).

Dependencies:
    - opentelemetry-api: Tracer and span API.
    - opentelemetry-sdk: TracerProvider, span processors, exporters.
    - opentelemetry-exporter-otlp-proto-grpc: OTLP gRPC exporter.
    - opentelemetry-instrumentation-fastapi: Auto-instrument FastAPI routes.
    - opentelemetry-instrumentation-sqlalchemy: Auto-instrument DB queries.
    - opentelemetry-instrumentation-httpx: Auto-instrument httpx HTTP calls.

Error conditions:
    - If OTEL_EXPORTER_OTLP_ENDPOINT is not set, tracing is disabled (no-op).
    - If the exporter is unreachable, traces are dropped silently (non-blocking).

Example:
    from services.api.infrastructure.tracing import setup_tracing, get_tracer
    setup_tracing()
    tracer = get_tracer()
    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("deployment_id", "dep-001")
        result = do_work()
"""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)

# Module-level flag: whether tracing has been initialized.
_tracing_initialized = False


def setup_tracing() -> bool:
    """
    Initialize OpenTelemetry distributed tracing.

    Reads configuration from environment variables:
        - OTEL_EXPORTER_OTLP_ENDPOINT: gRPC endpoint (e.g., http://jaeger:4317).
          If empty or unset, tracing is disabled (no-op provider).
        - OTEL_SERVICE_NAME: Service name for traces (default: fxlab-api).
        - OTEL_TRACES_SAMPLER: Sampler type (default: parentbased_traceidratio).
        - OTEL_TRACES_SAMPLER_ARG: Sampling rate (default: 1.0 = 100%).

    Returns:
        True if tracing was initialized with a real exporter.
        False if tracing is disabled (OTEL endpoint not configured).

    Raises:
        Nothing — all errors are caught and logged. Tracing failure must
        never prevent the application from starting.

    Example:
        if setup_tracing():
            logger.info("Tracing enabled")
        else:
            logger.info("Tracing disabled (no OTEL endpoint)")
    """
    global _tracing_initialized  # noqa: PLW0603

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        logger.info(
            "tracing_disabled",
            reason="OTEL_EXPORTER_OTLP_ENDPOINT not set",
            component="tracing",
        )
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        service_name = os.environ.get("OTEL_SERVICE_NAME", "fxlab-api")
        sampler_arg = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG", "1.0"))

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": "0.1.0-bootstrap",
                "deployment.environment": os.environ.get("ENVIRONMENT", "development"),
            }
        )

        # Configure sampler based on rate
        trace_sampler = None
        if sampler_arg < 1.0:
            from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

            trace_sampler = TraceIdRatioBased(sampler_arg)
        # else: trace_sampler remains None for default always-on

        if trace_sampler is not None:
            provider = TracerProvider(resource=resource, sampler=trace_sampler)
        else:
            provider = TracerProvider(resource=resource)

        # Configure OTLP gRPC exporter
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            insecure=not endpoint.startswith("https"),
        )
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)

        # Set as global TracerProvider
        trace.set_tracer_provider(provider)

        # Auto-instrument frameworks (best-effort — each may fail independently)
        _auto_instrument_fastapi()
        _auto_instrument_sqlalchemy()
        _auto_instrument_httpx()

        _tracing_initialized = True

        logger.info(
            "tracing_initialized",
            endpoint=endpoint,
            service_name=service_name,
            sampling_rate=sampler_arg,
            component="tracing",
        )
        return True

    except Exception as exc:
        logger.warning(
            "tracing_setup_failed",
            error=str(exc),
            component="tracing",
            exc_info=True,
        )
        return False


def _auto_instrument_fastapi() -> None:
    """
    Auto-instrument FastAPI with OpenTelemetry.

    Creates spans for every HTTP request with route, method, and status code.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor().instrument()
        logger.debug("tracing_fastapi_instrumented", component="tracing")
    except Exception as exc:
        logger.debug(
            "tracing_fastapi_skipped",
            reason=str(exc),
            component="tracing",
        )


def _auto_instrument_sqlalchemy() -> None:
    """
    Auto-instrument SQLAlchemy with OpenTelemetry.

    Creates spans for every database query with SQL statement and duration.
    """
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument()
        logger.debug("tracing_sqlalchemy_instrumented", component="tracing")
    except Exception as exc:
        logger.debug(
            "tracing_sqlalchemy_skipped",
            reason=str(exc),
            component="tracing",
        )


def _auto_instrument_httpx() -> None:
    """
    Auto-instrument httpx with OpenTelemetry.

    Creates spans for every outbound HTTP call (broker REST API).
    """
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        logger.debug("tracing_httpx_instrumented", component="tracing")
    except Exception as exc:
        logger.debug(
            "tracing_httpx_skipped",
            reason=str(exc),
            component="tracing",
        )


class _NoOpSpan:
    """
    Minimal no-op span used when opentelemetry is not installed.

    Supports the same context-manager and attribute API as a real
    opentelemetry Span so calling code can use tracing idioms
    without import guards.
    """

    def set_attribute(self, key: str, value: object) -> None:
        """No-op: discards attributes silently."""

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class _NoOpTracer:
    """
    Minimal no-op tracer used when opentelemetry is not installed.

    Returned by get_tracer() when the opentelemetry package is missing,
    so that callers can unconditionally write:

        tracer = get_tracer("my-component")
        with tracer.start_as_current_span("op") as span:
            span.set_attribute("key", "value")

    without guarding against ImportError.
    """

    def __init__(self, name: str = "noop") -> None:
        self._name = name

    def start_as_current_span(self, name: str, **kwargs: object) -> _NoOpSpan:
        """Return a no-op span context manager."""
        return _NoOpSpan()


def get_tracer(name: str = "fxlab-api") -> object:
    """
    Get an OpenTelemetry tracer for manual span creation.

    If tracing is not initialized, returns a no-op tracer that creates
    no-op spans (safe to use without conditional checks).

    If the opentelemetry package is not installed, returns a lightweight
    no-op tracer that supports start_as_current_span() as a context
    manager and set_attribute() — allowing calling code to use tracing
    idioms unconditionally without import guards.

    Args:
        name: Tracer name, typically the module or component name.

    Returns:
        opentelemetry.trace.Tracer (real or no-op), or _NoOpTracer
        if the opentelemetry package is not available.

    Example:
        tracer = get_tracer("kill_switch")
        with tracer.start_as_current_span("activate_kill_switch") as span:
            span.set_attribute("scope", "deployment")
            do_work()
    """
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        logger.debug(
            "opentelemetry_not_installed",
            component="tracing",
            reason="opentelemetry package not available, returning no-op tracer",
        )
        return _NoOpTracer(name)


def shutdown_tracing() -> None:
    """
    Flush and shut down the tracer provider.

    Should be called during graceful shutdown to ensure all pending spans
    are exported before the process exits.

    Raises:
        Nothing — all errors are caught and logged.

    Example:
        shutdown_tracing()  # Called in GracefulLifecycleManager.shutdown()
    """
    global _tracing_initialized  # noqa: PLW0603

    if not _tracing_initialized:
        return

    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
        _tracing_initialized = False
        logger.info("tracing_shutdown_complete", component="tracing")
    except Exception as exc:
        logger.warning(
            "tracing_shutdown_failed",
            error=str(exc),
            component="tracing",
        )
