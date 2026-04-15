"""
Position sizing service interface (port).

Responsibilities:
- Define the abstract contract for dynamic position sizing.
- Serve as the dependency injection target for controllers and tests.

Does NOT:
- Implement sizing logic (service implementation responsibility).

Dependencies:
- None (pure interface).

Error conditions:
- ValidationError: missing required parameters for chosen method.

Example:
    service: PositionSizingServiceInterface = PositionSizingService()
    result = service.compute_size(request)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.position_sizing import SizingMethod, SizingRequest, SizingResult


class PositionSizingServiceInterface(ABC):
    """
    Port interface for dynamic position sizing computation.

    Responsibilities:
    - Compute recommended position sizes using various methods.
    - List available sizing methods.

    Does NOT:
    - Execute trades.
    - Access databases directly.
    """

    @abstractmethod
    def compute_size(self, request: SizingRequest) -> SizingResult:
        """
        Compute recommended position size based on the request method.

        Args:
            request: SizingRequest with method and parameters.

        Returns:
            SizingResult with recommended quantity, value, and reasoning.

        Raises:
            ValidationError: If required parameters for the method are missing.
        """
        ...

    @abstractmethod
    def get_available_methods(self) -> list[SizingMethod]:
        """
        List all available sizing methods.

        Returns:
            List of SizingMethod enum values.
        """
        ...
