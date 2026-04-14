"""Strategy IR interfaces."""

from abc import ABC, abstractmethod
from typing import Any


class IStrategyIR(ABC):
    """Interface for strategy intermediate representation."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Convert IR to dictionary representation."""
        pass


__all__ = ["IStrategyIR"]
