"""
Optimization domain contracts.
Defines data models for optimization runs, results, and parameter configurations.
"""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import Field

from libs.contracts.base import FXLabBaseModel
from libs.contracts.enums import OptimizationStatus


class OptimizationParameters(FXLabBaseModel):
    """Parameters controlling the optimization process."""
    population_size: int = Field(ge=1)
    generations: int = Field(ge=1)
    mutation_rate: float = Field(ge=0.0, le=1.0)
    crossover_rate: float = Field(ge=0.0, le=1.0)
    elite_size: int = Field(ge=0)
    constraints: dict[str, Any] = Field(default_factory=dict)


class OptimizationMetrics(FXLabBaseModel):
    """Metrics from an optimization run."""
    best_fitness: float
    generation_count: int
    convergence_rate: float | None = None
    diversity_score: float | None = None
    computation_time_seconds: float


class OptimizationResult(FXLabBaseModel):
    """A single optimization result candidate."""
    candidate_id: str
    fitness_score: float
    parameters: dict[str, Any]
    metrics: dict[str, float]
    generation: int


class OptimizationRunRequest(FXLabBaseModel):
    """Request to start a new optimization run."""
    strategy_id: str
    target_environment: Literal["paper", "live"]
    parameters: OptimizationParameters
    constraints: dict[str, Any] = Field(default_factory=dict)


class OptimizationRunResponse(FXLabBaseModel):
    """Response after initiating an optimization run."""
    run_id: str
    strategy_id: str
    status: OptimizationStatus
    created_at: datetime
    estimated_completion: datetime | None = None


class OptimizationResultsResponse(FXLabBaseModel):
    """Complete results from an optimization run."""
    run_id: str
    strategy_id: str
    status: OptimizationStatus
    started_at: datetime
    completed_at: datetime | None = None
    parameters: OptimizationParameters
    metrics: OptimizationMetrics | None = None
    top_candidates: list[OptimizationResult] = Field(default_factory=list)
    total_candidates: int = 0


class OptimizationStatusResponse(FXLabBaseModel):
    """Current status of an optimization run."""
    run_id: str
    status: OptimizationStatus
    progress_percent: float = Field(ge=0.0, le=100.0)
    current_generation: int | None = None
    total_generations: int | None = None
    best_fitness_so_far: float | None = None
    estimated_time_remaining_seconds: float | None = None
