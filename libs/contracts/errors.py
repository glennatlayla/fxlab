"""
Typed exception hierarchy for FXLab.

Responsibilities:
- Define a structured exception tree so each layer catches what it can handle
  and re-raises or wraps the rest.
- Provide domain-specific error semantics (not-found vs SoD vs transient).

Does NOT:
- Contain HTTP status codes (controller maps these).
- Contain business logic.

Hierarchy:
    FXLabError (base)
    ├── ValidationError        — malformed input, schema violation
    │   └── RiskGateRejectionError — order blocked by risk gate
    ├── NotFoundError          — resource does not exist
    ├── SeparationOfDutiesError — submitter == reviewer on governance action
    ├── StrategyNameConflictError — clone target name already exists (409)
    ├── AuthError              — authentication / authorisation failure
    ├── ExternalServiceError   — downstream API / DB failure
    │   ├── TransientError     — retriable subset
    │   └── CircuitOpenError   — circuit breaker tripped (fast-fail)
    ├── StateTransitionError   — invalid state machine transition
    ├── KillSwitchActiveError  — trading halted by active kill switch
    └── ConfigError            — missing / invalid configuration
"""


class FXLabError(Exception):
    """Base exception for all FXLab domain errors."""


class NotFoundError(FXLabError):
    """Resource not found."""


class ValidationError(FXLabError):
    """Validation failed."""


class SeparationOfDutiesError(FXLabError):
    """
    Submitter and reviewer must be different users.

    Raised when a governance action (approve, reject, review) is attempted
    by the same user who submitted the request.  Maps to HTTP 409 Conflict
    at the controller layer.
    """


class StrategyNameConflictError(FXLabError):
    """
    A strategy with the requested name already exists.

    Raised by ``StrategyService.clone_strategy`` (and any future write
    path that needs name-uniqueness semantics) when the operator-supplied
    ``new_name`` collides with an existing active strategy. Maps to
    HTTP 409 Conflict at the controller layer.

    The ``strategies.name`` column does not carry a database-level
    UNIQUE constraint (see :class:`libs.contracts.models.Strategy`), so
    the check is enforced at the service layer using a case-insensitive
    name lookup against the repository. This means a tight race between
    two concurrent clones with the same ``new_name`` could in principle
    let both succeed; that risk is bounded because the clone surface is
    operator-driven (a single human clicking a button), and the name
    collision will be visible immediately on the next list refresh.

    Attributes:
        name: The conflicting strategy name (case-preserved as supplied
            by the caller, for inclusion in the error response body).
    """

    def __init__(self, message: str, *, name: str = "") -> None:
        super().__init__(message)
        self.name = name


class AuthError(FXLabError):
    """Authentication or authorisation failure."""


class ExternalServiceError(FXLabError):
    """Downstream API or database operation failed."""


class TransientError(ExternalServiceError):
    """
    Retriable subset of ExternalServiceError.

    Raise for network timeouts, 429 rate-limit, 5xx server errors.
    Do NOT raise for 400, 401, 403, 404.
    """


class CircuitOpenError(ExternalServiceError):
    """
    Circuit breaker is open — broker is unresponsive.

    Raised when a call is attempted through a circuit breaker that has
    tripped due to consecutive failures. The caller should not retry
    immediately; the circuit will probe after recovery_timeout_s.

    Attributes:
        adapter_name: Name of the broker adapter whose circuit tripped.
        open_since: ISO 8601 timestamp of when the circuit opened.
        failure_count: Number of consecutive failures that triggered the trip.
    """

    def __init__(
        self,
        message: str,
        *,
        adapter_name: str = "",
        open_since: str = "",
        failure_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.adapter_name = adapter_name
        self.open_since = open_since
        self.failure_count = failure_count


class RiskGateRejectionError(ValidationError):
    """
    Order blocked by a pre-trade risk gate check.

    Raised when enforce_order() detects a risk limit breach.
    Includes the failing check details so the caller can identify
    exactly which risk limit was violated and by how much.

    Attributes:
        check_name: Name of the failing risk check (e.g. "order_value").
        severity: Risk event severity level.
        reason: Human-readable explanation of the violation.
        deployment_id: ULID of the deployment that was checked.
        order_client_id: Client order ID that was rejected.
        current_value: Actual value that exceeded the limit.
        limit_value: The configured limit that was breached.
    """

    def __init__(
        self,
        message: str,
        *,
        check_name: str = "",
        severity: str = "",
        reason: str = "",
        deployment_id: str = "",
        order_client_id: str = "",
        current_value: str = "",
        limit_value: str = "",
    ) -> None:
        super().__init__(message)
        self.check_name = check_name
        self.severity = severity
        self.reason = reason
        self.deployment_id = deployment_id
        self.order_client_id = order_client_id
        self.current_value = current_value
        self.limit_value = limit_value


class StateTransitionError(FXLabError):
    """
    Invalid state machine transition attempted.

    Raised when a deployment (or other stateful entity) attempts a transition
    that is not permitted by the state machine rules.  Maps to HTTP 409
    Conflict at the controller layer.

    Attributes:
        current_state: The entity's current state.
        attempted_state: The state the caller tried to move to.
    """

    def __init__(
        self,
        message: str,
        *,
        current_state: str | None = None,
        attempted_state: str | None = None,
    ) -> None:
        super().__init__(message)
        self.current_state = current_state
        self.attempted_state = attempted_state


class KillSwitchActiveError(FXLabError):
    """
    Trading halted by an active kill switch.

    Raised when an order submission is attempted but a kill switch is active
    at any applicable scope (global, strategy, or symbol). The caller must
    not retry — the kill switch must be explicitly deactivated first.

    Attributes:
        scope: Kill switch scope that triggered the halt (global/strategy/symbol).
        target_id: Identifier of the halted target.
        deployment_id: ULID of the deployment that was blocked.
    """

    def __init__(
        self,
        message: str,
        *,
        scope: str = "",
        target_id: str = "",
        deployment_id: str = "",
    ) -> None:
        super().__init__(message)
        self.scope = scope
        self.target_id = target_id
        self.deployment_id = deployment_id


class ConfigError(FXLabError):
    """Missing or invalid configuration."""


class IndicatorNotFoundError(NotFoundError):
    """
    Requested indicator name is not registered in the indicator engine.

    Raised when ``IndicatorEngine.compute()`` or ``compute_batch()`` is called
    with an indicator name that has not been registered via the indicator
    registry.

    Attributes:
        indicator_name: The unregistered indicator name that was requested.
        available: List of registered indicator names (for error messages).
    """

    def __init__(
        self,
        indicator_name: str,
        *,
        available: list[str] | None = None,
    ) -> None:
        available_str = ", ".join(sorted(available)) if available else "none"
        super().__init__(
            f"Indicator '{indicator_name}' is not registered. Available indicators: {available_str}"
        )
        self.indicator_name = indicator_name
        self.available = available or []
