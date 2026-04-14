"""
Strategy compiler interfaces.
"""

from abc import ABC, abstractmethod

from libs.contracts.strategy import CompiledStrategy, StrategyDefinition

__all__ = [
    "IStrategyCompiler",
    "StrategyDefinition",
    "CompiledStrategy",
]


class IStrategyCompiler(ABC):
    """Interface for compiling strategy definitions."""

    @abstractmethod
    async def compile(self, definition: StrategyDefinition) -> CompiledStrategy:
        """Compile a strategy definition into executable form."""
        ...

    @abstractmethod
    async def validate(self, definition: StrategyDefinition) -> bool:
        """Validate a strategy definition without compiling."""
        ...
