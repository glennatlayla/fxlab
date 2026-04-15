"""
Broker timeout configuration for external API calls.

Responsibilities:
- Define timeout values for broker communication operations.
- Load overrides from environment variables with sensible defaults.
- Provide a single source of truth for all timeout parameters.

Does NOT:
- Execute any I/O or network calls.
- Enforce timeouts (that is the adapter's responsibility).
- Contain retry logic (see task_retry.py for that).

Dependencies:
- os: Environment variable access.
- dataclasses: Immutable configuration container.

Error conditions:
- None raised directly. Invalid environment values fall back to defaults.

Example:
    config = BrokerTimeoutConfig.from_env()
    # config.connect_timeout_s == 5.0 (or BROKER_CONNECT_TIMEOUT env value)
    # config.order_timeout_s == 30.0 (or BROKER_ORDER_TIMEOUT env value)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BrokerTimeoutConfig:
    """
    Immutable timeout configuration for broker adapter operations.

    All values are in seconds. Each timeout applies to a different class
    of broker interaction, reflecting the different latency profiles of
    connection setup, data reads, and order lifecycle operations.

    Attributes:
        connect_timeout_s: TCP connection establishment timeout.
            Applies to initial socket connection. Default 5.0s.
        read_timeout_s: Response read timeout for data queries.
            Applies to get_order, list_open_orders, get_positions, etc.
            Default 10.0s.
        order_timeout_s: Timeout for order submission and cancellation.
            Longer than read because order routing may involve multiple
            exchange hops. Default 30.0s.
        cancel_timeout_s: Timeout for order cancel requests.
            Shorter than order_timeout_s because cancel does not require
            fill confirmation. Default 15.0s.
        stream_heartbeat_s: Maximum interval between WebSocket heartbeats.
            If no heartbeat is received within this period, the stream
            connection is considered dead and must be reconnected.
            Default 30.0s.

    Example:
        config = BrokerTimeoutConfig()
        # Uses all defaults: 5.0, 10.0, 30.0, 15.0, 30.0

        config = BrokerTimeoutConfig(connect_timeout_s=3.0, order_timeout_s=20.0)
        # Override specific values, rest use defaults

        config = BrokerTimeoutConfig.from_env()
        # Load from BROKER_* environment variables with defaults
    """

    connect_timeout_s: float = 5.0
    read_timeout_s: float = 10.0
    order_timeout_s: float = 30.0
    cancel_timeout_s: float = 15.0
    stream_heartbeat_s: float = 30.0

    @classmethod
    def from_env(cls) -> BrokerTimeoutConfig:
        """
        Create a BrokerTimeoutConfig from environment variables.

        Reads the following environment variables (all optional):
        - BROKER_CONNECT_TIMEOUT: connect_timeout_s (default: 5.0)
        - BROKER_READ_TIMEOUT: read_timeout_s (default: 10.0)
        - BROKER_ORDER_TIMEOUT: order_timeout_s (default: 30.0)
        - BROKER_CANCEL_TIMEOUT: cancel_timeout_s (default: 15.0)
        - BROKER_STREAM_HEARTBEAT: stream_heartbeat_s (default: 30.0)

        Invalid (non-numeric) values are silently ignored and the default
        is used, with a warning logged.

        Returns:
            BrokerTimeoutConfig populated from environment.

        Example:
            # With BROKER_ORDER_TIMEOUT=20 in environment:
            config = BrokerTimeoutConfig.from_env()
            # config.order_timeout_s == 20.0
        """
        defaults = cls()
        env_mapping = {
            "BROKER_CONNECT_TIMEOUT": ("connect_timeout_s", defaults.connect_timeout_s),
            "BROKER_READ_TIMEOUT": ("read_timeout_s", defaults.read_timeout_s),
            "BROKER_ORDER_TIMEOUT": ("order_timeout_s", defaults.order_timeout_s),
            "BROKER_CANCEL_TIMEOUT": ("cancel_timeout_s", defaults.cancel_timeout_s),
            "BROKER_STREAM_HEARTBEAT": ("stream_heartbeat_s", defaults.stream_heartbeat_s),
        }

        kwargs: dict[str, float] = {}
        for env_var, (field_name, default_val) in env_mapping.items():
            raw = os.environ.get(env_var)
            if raw is not None:
                try:
                    parsed = float(raw)
                    if parsed <= 0:
                        logger.warning(
                            "timeout_config.non_positive_value",
                            env_var=env_var,
                            raw_value=raw,
                            component="timeout_config",
                            detail=f"Value must be positive. Using default {default_val}.",
                        )
                        kwargs[field_name] = default_val
                    else:
                        kwargs[field_name] = parsed
                except ValueError:
                    logger.warning(
                        "timeout_config.invalid_value",
                        env_var=env_var,
                        raw_value=raw,
                        component="timeout_config",
                        detail=f"Cannot parse as float. Using default {default_val}.",
                    )
                    kwargs[field_name] = default_val
            else:
                kwargs[field_name] = default_val

        return cls(**kwargs)
