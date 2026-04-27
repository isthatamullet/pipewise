"""CostBudgetScorer + LatencyBudgetScorer — RunScorers for cost/latency caps.

Both have the same shape: read a `total_*` field off the `PipelineRun`, pass
when it's at or below the configured budget, fail otherwise. They live in
the same module because they're variations of one pattern; splitting them
into separate files would just duplicate the boilerplate.

Behavior when the field is None (e.g., the adapter didn't capture cost):
- `on_missing="fail"` (default): score=0, passed=False, reasoning explains.
- `on_missing="skip"`: score=1, passed=True, reasoning notes the skip.

`"fail"` is the default because silent passing on missing data masks
real problems — if you've configured a cost budget, you want to know when
the adapter forgot to capture costs, not have your eval pretend everything
is fine.
"""

from typing import Literal

from pipewise.core.schema import PipelineRun
from pipewise.core.scorer import ScoreResult

OnMissing = Literal["fail", "skip"]


class CostBudgetScorer:
    """RunScorer: pass when `run.total_cost_usd <= budget_usd`."""

    def __init__(
        self,
        budget_usd: float,
        *,
        on_missing: OnMissing = "fail",
        name: str | None = None,
    ) -> None:
        if budget_usd < 0:
            raise ValueError("budget_usd must be non-negative")
        self.budget_usd = budget_usd
        self.on_missing = on_missing
        self.name = name or f"cost_budget[{budget_usd}]"

    def score(
        self,
        actual: PipelineRun,
        expected: PipelineRun | None = None,
    ) -> ScoreResult:
        cost = actual.total_cost_usd
        if cost is None:
            return _missing_result(
                field="total_cost_usd",
                on_missing=self.on_missing,
                budget=self.budget_usd,
                unit="usd",
            )

        passed = cost <= self.budget_usd
        return ScoreResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            reasoning=(
                None
                if passed
                else f"total_cost_usd {cost} exceeds budget {self.budget_usd}"
            ),
            metadata={
                "actual": cost,
                "budget": self.budget_usd,
                "unit": "usd",
            },
        )


class LatencyBudgetScorer:
    """RunScorer: pass when `run.total_latency_ms <= budget_ms`."""

    def __init__(
        self,
        budget_ms: int,
        *,
        on_missing: OnMissing = "fail",
        name: str | None = None,
    ) -> None:
        if budget_ms < 0:
            raise ValueError("budget_ms must be non-negative")
        self.budget_ms = budget_ms
        self.on_missing = on_missing
        self.name = name or f"latency_budget[{budget_ms}ms]"

    def score(
        self,
        actual: PipelineRun,
        expected: PipelineRun | None = None,
    ) -> ScoreResult:
        latency = actual.total_latency_ms
        if latency is None:
            return _missing_result(
                field="total_latency_ms",
                on_missing=self.on_missing,
                budget=self.budget_ms,
                unit="ms",
            )

        passed = latency <= self.budget_ms
        return ScoreResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            reasoning=(
                None
                if passed
                else f"total_latency_ms {latency} exceeds budget {self.budget_ms}"
            ),
            metadata={
                "actual": latency,
                "budget": self.budget_ms,
                "unit": "ms",
            },
        )


def _missing_result(
    *,
    field: str,
    on_missing: OnMissing,
    budget: float | int,
    unit: str,
) -> ScoreResult:
    if on_missing == "skip":
        return ScoreResult(
            score=1.0,
            passed=True,
            reasoning=f"{field} is None; on_missing='skip' so scorer passes",
            metadata={"missing": True, "budget": budget, "unit": unit},
        )
    return ScoreResult(
        score=0.0,
        passed=False,
        reasoning=(
            f"{field} is None; budget cannot be evaluated "
            "(set on_missing='skip' to allow this)"
        ),
        metadata={"missing": True, "budget": budget, "unit": unit},
    )


__all__ = ["CostBudgetScorer", "LatencyBudgetScorer", "OnMissing"]
