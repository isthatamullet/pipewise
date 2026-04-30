"""Tests for `CostBudgetScorer` and `LatencyBudgetScorer`."""

from datetime import UTC, datetime, timedelta

import pytest

from pipewise import PipelineRun, RunScorer, StepExecution
from pipewise.scorers.budget import CostBudgetScorer, LatencyBudgetScorer

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _run(
    *,
    total_cost_usd: float | None = None,
    total_latency_ms: int | None = None,
) -> PipelineRun:
    return PipelineRun(
        run_id="r1",
        pipeline_name="example",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=10),
        status="completed",
        steps=[
            StepExecution(
                step_id="s1",
                step_name="S1",
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=1),
                status="completed",
            )
        ],
        adapter_name="example-adapter",
        adapter_version="0.1.0",
        total_cost_usd=total_cost_usd,
        total_latency_ms=total_latency_ms,
    )


class TestCostBudgetScorer:
    def test_satisfies_run_scorer_protocol(self) -> None:
        assert isinstance(CostBudgetScorer(budget_usd=1.0), RunScorer)

    def test_under_budget_passes(self) -> None:
        result = CostBudgetScorer(budget_usd=1.0).score(_run(total_cost_usd=0.5))
        assert result.status == "passed"
        assert result.score == 1.0

    def test_at_budget_passes(self) -> None:
        result = CostBudgetScorer(budget_usd=1.0).score(_run(total_cost_usd=1.0))
        assert result.status == "passed"

    def test_over_budget_fails(self) -> None:
        result = CostBudgetScorer(budget_usd=1.0).score(_run(total_cost_usd=1.5))
        assert result.status == "failed"
        assert result.score == 0.0
        assert "exceeds budget" in (result.reasoning or "")
        assert result.metadata == {"actual": 1.5, "budget": 1.0, "unit": "usd"}

    def test_zero_budget_zero_cost_passes(self) -> None:
        result = CostBudgetScorer(budget_usd=0.0).score(_run(total_cost_usd=0.0))
        assert result.status == "passed"

    def test_missing_cost_fails_by_default(self) -> None:
        result = CostBudgetScorer(budget_usd=1.0).score(_run(total_cost_usd=None))
        assert result.status == "failed"
        assert "is None" in (result.reasoning or "")
        assert result.metadata["missing"] is True

    def test_missing_cost_with_skip_emits_skipped(self) -> None:
        result = CostBudgetScorer(budget_usd=1.0, on_missing="skip").score(
            _run(total_cost_usd=None)
        )
        assert result.status == "skipped"
        assert result.score is None
        assert "did not evaluate" in (result.reasoning or "")
        assert result.metadata["missing"] is True

    def test_negative_budget_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            CostBudgetScorer(budget_usd=-0.01)

    def test_default_name(self) -> None:
        assert CostBudgetScorer(budget_usd=2.5).name == "cost_budget[2.5]"

    def test_custom_name(self) -> None:
        assert CostBudgetScorer(budget_usd=1.0, name="strict_cost").name == "strict_cost"


class TestLatencyBudgetScorer:
    def test_satisfies_run_scorer_protocol(self) -> None:
        assert isinstance(LatencyBudgetScorer(budget_ms=1000), RunScorer)

    def test_under_budget_passes(self) -> None:
        result = LatencyBudgetScorer(budget_ms=1000).score(_run(total_latency_ms=500))
        assert result.status == "passed"

    def test_at_budget_passes(self) -> None:
        result = LatencyBudgetScorer(budget_ms=1000).score(_run(total_latency_ms=1000))
        assert result.status == "passed"

    def test_over_budget_fails(self) -> None:
        result = LatencyBudgetScorer(budget_ms=1000).score(_run(total_latency_ms=1500))
        assert result.status == "failed"
        assert "exceeds budget" in (result.reasoning or "")
        assert result.metadata == {"actual": 1500, "budget": 1000, "unit": "ms"}

    def test_missing_latency_fails_by_default(self) -> None:
        result = LatencyBudgetScorer(budget_ms=1000).score(_run(total_latency_ms=None))
        assert result.status == "failed"
        assert result.metadata["missing"] is True

    def test_missing_latency_with_skip_emits_skipped(self) -> None:
        result = LatencyBudgetScorer(budget_ms=1000, on_missing="skip").score(
            _run(total_latency_ms=None)
        )
        assert result.status == "skipped"
        assert result.score is None

    def test_negative_budget_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            LatencyBudgetScorer(budget_ms=-1)

    def test_default_name(self) -> None:
        assert LatencyBudgetScorer(budget_ms=2000).name == "latency_budget[2000ms]"

    def test_custom_name(self) -> None:
        assert LatencyBudgetScorer(budget_ms=1000, name="p95").name == "p95"
