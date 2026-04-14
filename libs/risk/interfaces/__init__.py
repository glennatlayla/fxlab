"""Risk management interfaces."""

from abc import ABC, abstractmethod
from typing import Any


class IRiskCalculator(ABC):
    """Interface for risk calculations."""

    @abstractmethod
    async def calculate_risk(self, **kwargs) -> dict[str, Any]:
        """Calculate risk metrics."""
        pass


__all__ = ["IRiskCalculator"]
