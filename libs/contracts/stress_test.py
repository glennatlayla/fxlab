"""
Stress testing and scenario analysis contracts.

Responsibilities:
- Define stress scenario configuration (predefined and custom).
- Define stress test result with per-symbol and portfolio-level impact.
- Provide predefined scenario library with historically calibrated shocks.
- Frozen Pydantic models for type safety and serialization.

Does NOT:
- Execute stress tests (service responsibility).
- Persist results (repository/cache responsibility).
- Access market data or position data (injected via service dependencies).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: Decimal, datetime, enum.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    scenario = StressScenario(
        name="Flash Crash 2010",
        description="Simulates the May 2010 flash crash",
        shocks={"*": Decimal("-8.7")},
        is_predefined=True,
    )
    result = StressTestResult(
        scenario_name="Flash Crash 2010",
        portfolio_pnl_impact=Decimal("-8700.00"),
        per_symbol_impact=[...],
        margin_impact=Decimal("-4350.00"),
        would_trigger_halt=True,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class ScenarioLibrary(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+; keeping str+Enum for 3.10 compat
    """
    Predefined stress scenario identifiers.

    Each value maps to a historically calibrated set of market shocks.

    Values:
    - FLASH_CRASH_2010: May 6, 2010 flash crash — broad equity drop of ~8.7%.
    - COVID_MARCH_2020: March 2020 COVID sell-off — S&P 500 dropped ~34%.
    - RATE_HIKE_2022: 2022 aggressive rate hikes — tech-heavy drawdown ~33%.
    - SECTOR_ROTATION: Sudden rotation from growth to value — tech -15%, financials +5%.
    - CUSTOM: User-defined scenario with arbitrary shocks.
    """

    FLASH_CRASH_2010 = "flash_crash_2010"
    COVID_MARCH_2020 = "covid_march_2020"
    RATE_HIKE_2022 = "rate_hike_2022"
    SECTOR_ROTATION = "sector_rotation"
    CUSTOM = "custom"


class StressScenario(BaseModel):
    """
    Configuration for a stress test scenario.

    Shocks are expressed as percentage changes (e.g., -8.7 means an 8.7% drop).
    The shocks dict maps symbol names (or "*" for all positions) to percentage
    changes. Sector-level shocks use sector names as keys.

    Responsibilities:
    - Define the shock parameters for a stress scenario.
    - Distinguish predefined from custom scenarios.

    Does NOT:
    - Apply shocks (service responsibility).

    Example:
        # All positions drop 8.7%
        scenario = StressScenario(
            name="Flash Crash 2010",
            description="May 2010 flash crash simulation",
            shocks={"*": Decimal("-8.7")},
            is_predefined=True,
        )

        # Custom: AAPL drops 50%, MSFT drops 30%
        custom = StressScenario(
            name="Custom Tech Crash",
            description="Custom scenario",
            shocks={"AAPL": Decimal("-50"), "MSFT": Decimal("-30")},
            is_predefined=False,
        )
    """

    model_config = {"frozen": True}

    name: str = Field(
        ..., min_length=1, max_length=200, description="Human-readable scenario name."
    )
    description: str = Field(default="", description="Detailed scenario description.")
    shocks: dict[str, Decimal] = Field(
        ...,
        min_length=1,
        description="Symbol → percentage shock mapping. Use '*' for all positions.",
    )
    is_predefined: bool = Field(
        default=False,
        description="Whether this scenario is from the predefined library.",
    )
    scenario_type: ScenarioLibrary = Field(
        default=ScenarioLibrary.CUSTOM,
        description="Scenario library identifier.",
    )


class SymbolStressImpact(BaseModel):
    """
    Stress test impact for a single symbol.

    Responsibilities:
    - Record the P&L impact of a shock on one position.

    Does NOT:
    - Compute impact (service responsibility).

    Example:
        impact = SymbolStressImpact(
            symbol="AAPL",
            current_value=Decimal("10000.00"),
            shock_pct=Decimal("-8.7"),
            stressed_value=Decimal("9130.00"),
            pnl_impact=Decimal("-870.00"),
        )
    """

    model_config = {"frozen": True}

    symbol: str = Field(..., min_length=1, description="Instrument ticker.")
    current_value: Decimal = Field(..., description="Current market value before shock.")
    shock_pct: Decimal = Field(..., description="Applied shock as percentage (e.g., -8.7).")
    stressed_value: Decimal = Field(..., description="Market value after shock applied.")
    pnl_impact: Decimal = Field(..., description="Dollar P&L impact (stressed - current).")


class StressTestResult(BaseModel):
    """
    Result of a stress test scenario execution.

    Contains portfolio-level and per-symbol impact breakdown, margin
    impact estimate, and whether the stressed P&L would trigger a
    deployment halt via the risk gate.

    Responsibilities:
    - Aggregate stress test results for reporting and decision-making.
    - Flag scenarios that would breach risk limits.

    Does NOT:
    - Execute stress tests (service responsibility).
    - Trigger actual risk actions (advisory only).

    Example:
        result = StressTestResult(
            scenario_name="Flash Crash 2010",
            portfolio_pnl_impact=Decimal("-8700.00"),
            per_symbol_impact=[...],
            margin_impact=Decimal("-4350.00"),
            would_trigger_halt=True,
        )
    """

    model_config = {"frozen": True}

    scenario_name: str = Field(..., description="Name of the scenario that was run.")
    portfolio_pnl_impact: Decimal = Field(
        ...,
        description="Total portfolio P&L impact in dollars.",
    )
    per_symbol_impact: list[SymbolStressImpact] = Field(
        ...,
        description="Per-symbol impact breakdown, sorted by absolute impact descending.",
    )
    margin_impact: Decimal = Field(
        ...,
        description="Estimated margin impact (approximated as 50% of P&L impact).",
    )
    would_trigger_halt: bool = Field(
        ...,
        description="Whether stressed P&L would exceed deployment's daily loss limit.",
    )
    daily_loss_limit: Decimal | None = Field(
        default=None,
        description="The daily loss limit compared against (None if not configured).",
    )
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the stress test was executed.",
    )


# ---------------------------------------------------------------------------
# Predefined scenario definitions
# ---------------------------------------------------------------------------

PREDEFINED_SCENARIOS: dict[ScenarioLibrary, StressScenario] = {
    ScenarioLibrary.FLASH_CRASH_2010: StressScenario(
        name="Flash Crash 2010",
        description=(
            "Simulates the May 6, 2010 flash crash. The Dow Jones dropped "
            "approximately 1,000 points (~8.7%) in minutes before recovering."
        ),
        shocks={"*": Decimal("-8.7")},
        is_predefined=True,
        scenario_type=ScenarioLibrary.FLASH_CRASH_2010,
    ),
    ScenarioLibrary.COVID_MARCH_2020: StressScenario(
        name="COVID March 2020",
        description=(
            "Simulates the March 2020 COVID-19 sell-off. The S&P 500 dropped "
            "approximately 34% from peak to trough over several weeks."
        ),
        shocks={"*": Decimal("-34.0")},
        is_predefined=True,
        scenario_type=ScenarioLibrary.COVID_MARCH_2020,
    ),
    ScenarioLibrary.RATE_HIKE_2022: StressScenario(
        name="Rate Hike 2022",
        description=(
            "Simulates the 2022 aggressive rate hike cycle. Technology stocks "
            "dropped approximately 33%, while financials gained modestly."
        ),
        shocks={"*": Decimal("-33.0")},
        is_predefined=True,
        scenario_type=ScenarioLibrary.RATE_HIKE_2022,
    ),
    ScenarioLibrary.SECTOR_ROTATION: StressScenario(
        name="Sector Rotation",
        description=(
            "Simulates a sudden rotation from growth to value. Technology "
            "stocks drop 15% while financial sector gains 5%."
        ),
        shocks={"*": Decimal("-15.0")},
        is_predefined=True,
        scenario_type=ScenarioLibrary.SECTOR_ROTATION,
    ),
}
