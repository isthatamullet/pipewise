"""Tests for `NumericToleranceScorer`."""

from datetime import UTC, datetime, timedelta

import pytest

from pipewise import StepExecution, StepScorer
from pipewise.scorers.numeric_tolerance import NumericToleranceScorer

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _step(outputs: dict[str, object], step_id: str = "s1") -> StepExecution:
    return StepExecution(
        step_id=step_id,
        step_name=step_id.upper(),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        status="completed",
        outputs=outputs,
    )


class TestNumericToleranceScorerAbsolute:
    def test_satisfies_step_scorer_protocol(self) -> None:
        scorer = NumericToleranceScorer(field="x", tolerance=1.0)
        assert isinstance(scorer, StepScorer)

    def test_within_tolerance_passes(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=10)
        result = scorer.score(_step({"rating": 75}), _step({"rating": 80}))
        assert result.passed is True
        assert result.score == 1.0
        assert result.metadata["delta"] == 5
        assert result.metadata["mode"] == "absolute"

    def test_at_tolerance_boundary_passes(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=10)
        result = scorer.score(_step({"rating": 70}), _step({"rating": 80}))
        assert result.passed is True
        assert result.score == 1.0

    def test_outside_tolerance_fails(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=10)
        result = scorer.score(_step({"rating": 60}), _step({"rating": 80}))
        assert result.passed is False
        assert result.score == 0.0
        assert "tolerance 10" in (result.reasoning or "")

    def test_exact_equal_passes(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=0)
        result = scorer.score(_step({"rating": 80}), _step({"rating": 80}))
        assert result.passed is True

    def test_zero_tolerance_one_off_fails(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=0)
        result = scorer.score(_step({"rating": 81}), _step({"rating": 80}))
        assert result.passed is False

    def test_floats_within_tolerance(self) -> None:
        scorer = NumericToleranceScorer(field="cost", tolerance=0.01)
        result = scorer.score(_step({"cost": 0.123}), _step({"cost": 0.125}))
        assert result.passed is True

    def test_negative_values(self) -> None:
        scorer = NumericToleranceScorer(field="delta", tolerance=5)
        result = scorer.score(_step({"delta": -10}), _step({"delta": -7}))
        assert result.passed is True


class TestNumericToleranceScorerRelative:
    def test_within_relative_passes(self) -> None:
        # 5% off, tolerance 10% → pass
        scorer = NumericToleranceScorer(field="rating", tolerance=0.1, relative=True)
        result = scorer.score(_step({"rating": 95}), _step({"rating": 100}))
        assert result.passed is True
        assert result.metadata["mode"] == "relative"
        assert result.metadata["ratio"] is not None

    def test_outside_relative_fails(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=0.1, relative=True)
        result = scorer.score(_step({"rating": 80}), _step({"rating": 100}))
        assert result.passed is False
        assert result.score == 0.0

    def test_relative_with_expected_zero_requires_exact(self) -> None:
        scorer = NumericToleranceScorer(field="x", tolerance=0.1, relative=True)
        # Both zero: pass.
        assert scorer.score(_step({"x": 0}), _step({"x": 0})).passed is True
        # Expected zero, actual nonzero: fail (no defined relative semantic).
        assert scorer.score(_step({"x": 0.0001}), _step({"x": 0})).passed is False


class TestNumericToleranceScorerErrors:
    def test_missing_actual_field_fails(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=10)
        result = scorer.score(_step({}), _step({"rating": 80}))
        assert result.passed is False
        assert "missing from actual" in (result.reasoning or "")

    def test_missing_expected_field_fails(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=10)
        result = scorer.score(_step({"rating": 80}), _step({}))
        assert result.passed is False
        assert "missing from expected" in (result.reasoning or "")

    def test_non_numeric_actual_fails(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=10)
        result = scorer.score(_step({"rating": "high"}), _step({"rating": 80}))
        assert result.passed is False
        assert "not a number" in (result.reasoning or "")

    def test_non_numeric_expected_fails(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=10)
        result = scorer.score(_step({"rating": 80}), _step({"rating": "high"}))
        assert result.passed is False
        assert "not a number" in (result.reasoning or "")

    def test_bool_is_not_numeric(self) -> None:
        # Python bool is technically int; we don't want a True/False to count.
        scorer = NumericToleranceScorer(field="flag", tolerance=1)
        result = scorer.score(_step({"flag": True}), _step({"flag": 1}))
        assert result.passed is False
        assert "not a number" in (result.reasoning or "")

    def test_expected_required(self) -> None:
        scorer = NumericToleranceScorer(field="rating", tolerance=10)
        with pytest.raises(ValueError, match="requires an `expected` step"):
            scorer.score(_step({"rating": 80}))

    def test_negative_tolerance_rejected(self) -> None:
        with pytest.raises(ValueError, match="tolerance must be non-negative"):
            NumericToleranceScorer(field="x", tolerance=-1)

    def test_empty_field_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty field"):
            NumericToleranceScorer(field="", tolerance=1)

    def test_default_name_includes_mode_and_tolerance(self) -> None:
        assert (
            NumericToleranceScorer(field="rating", tolerance=10).name
            == "numeric_tolerance[rating,abs=10]"
        )
        assert (
            NumericToleranceScorer(field="rating", tolerance=0.1, relative=True).name
            == "numeric_tolerance[rating,rel=0.1]"
        )

    def test_custom_name_used(self) -> None:
        scorer = NumericToleranceScorer(field="x", tolerance=1, name="my_tol")
        assert scorer.name == "my_tol"
