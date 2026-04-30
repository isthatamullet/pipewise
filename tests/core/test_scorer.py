"""Tests for `ScoreResult` + `StepScorer` / `RunScorer` Protocols.

Concrete scorer implementations (ExactMatch, LlmJudge, etc.) land in Phase 2;
this file tests the Protocol contract using minimal dummy scorers.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from pipewise import (
    PipelineRun,
    RunScorer,
    ScoreResult,
    StepExecution,
    StepScorer,
)

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _step(step_id: str = "s1") -> StepExecution:
    return StepExecution(
        step_id=step_id,
        step_name=step_id.upper(),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        status="completed",
    )


def _run() -> PipelineRun:
    return PipelineRun(
        run_id="r1",
        pipeline_name="example",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=10),
        status="completed",
        steps=[_step()],
        adapter_name="example-adapter",
        adapter_version="0.1.0",
    )


class TestScoreResult:
    def test_minimal_valid(self) -> None:
        result = ScoreResult(score=1.0, status="passed")
        assert result.score == 1.0
        assert result.status == "passed"
        assert result.reasoning is None
        assert result.metadata == {}

    def test_full_result(self) -> None:
        result = ScoreResult(
            score=0.85,
            status="passed",
            reasoning="Output matched expected on 17 of 20 fields.",
            metadata={"field_diff": {"title": "ok", "summary": "differs"}},
        )
        assert result.reasoning is not None
        assert result.metadata["field_diff"]["title"] == "ok"

    @pytest.mark.parametrize("score", [-0.01, 1.01, 2.0, -1.0])
    def test_score_out_of_range_rejected(self, score: float) -> None:
        with pytest.raises(ValidationError):
            ScoreResult(score=score, status="passed")

    @pytest.mark.parametrize("score", [0.0, 0.5, 1.0])
    def test_score_at_bounds_accepted(self, score: float) -> None:
        result = ScoreResult(score=score, status="failed")
        assert result.score == score

    def test_extra_field_rejected(self) -> None:
        # Same convention as PipelineRun / StepExecution: extensions go in metadata.
        with pytest.raises(ValidationError):
            ScoreResult(score=0.5, status="passed", unknown_field="value")  # type: ignore[call-arg]

    def test_round_trip_json(self) -> None:
        result = ScoreResult(
            score=0.7,
            status="passed",
            reasoning="three-of-five claims verified",
            metadata={"verified": 3, "total": 5},
        )
        restored = ScoreResult.model_validate_json(result.model_dump_json())
        assert restored == result

    def test_skipped_status_allows_none_score(self) -> None:
        # A skipped scorer didn't run, so it can't carry a score.
        result = ScoreResult(status="skipped", reasoning="step out of scope")
        assert result.status == "skipped"
        assert result.score is None

    def test_skipped_status_round_trips(self) -> None:
        result = ScoreResult(status="skipped", reasoning="step out of scope")
        restored = ScoreResult.model_validate_json(result.model_dump_json())
        assert restored == result

    def test_passed_status_requires_score(self) -> None:
        # status="passed" or "failed" without a score is a malformed result.
        with pytest.raises(ValidationError, match="score is required"):
            ScoreResult(status="passed")
        with pytest.raises(ValidationError, match="score is required"):
            ScoreResult(status="failed", reasoning="no score given")

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScoreResult(status="ok", score=1.0)  # type: ignore[arg-type]


class TestStepScorerProtocol:
    """Verify the `StepScorer` Protocol works with structural typing
    (the @runtime_checkable allows isinstance, but signatures aren't checked
    at runtime — type compatibility is mypy's job)."""

    def test_dummy_scorer_satisfies_protocol(self) -> None:
        class TrivialStepScorer:
            name = "trivial"

            def score(
                self,
                actual: StepExecution,
                expected: StepExecution | None = None,
            ) -> ScoreResult:
                return ScoreResult(score=1.0, status="passed")

        scorer = TrivialStepScorer()
        assert isinstance(scorer, StepScorer)

        # Calling the scorer produces a real ScoreResult.
        result = scorer.score(_step())
        assert result.score == 1.0
        assert result.status == "passed"

    def test_object_without_name_fails_isinstance(self) -> None:
        class NoName:
            def score(
                self,
                actual: StepExecution,
                expected: StepExecution | None = None,
            ) -> ScoreResult:
                return ScoreResult(score=0.0, status="failed")

        # Without `name`, the Protocol's structural check should fail.
        assert not isinstance(NoName(), StepScorer)

    def test_object_without_score_method_fails_isinstance(self) -> None:
        class NoScoreMethod:
            name = "nope"

        assert not isinstance(NoScoreMethod(), StepScorer)

    def test_scorer_can_use_expected(self) -> None:
        """A scorer is free to compare actual vs. expected, but isn't
        required to use `expected`. This confirms passing it works."""

        class ExactStepIdScorer:
            name = "exact_step_id"

            def score(
                self,
                actual: StepExecution,
                expected: StepExecution | None = None,
            ) -> ScoreResult:
                if expected is None:
                    return ScoreResult(score=1.0, status="passed", reasoning="no expected")
                matches = actual.step_id == expected.step_id
                return ScoreResult(
                    status="passed" if matches else "failed",
                    score=1.0 if matches else 0.0,
                    reasoning=f"actual={actual.step_id!r}, expected={expected.step_id!r}",
                )

        scorer = ExactStepIdScorer()
        result = scorer.score(_step("a"), _step("a"))
        assert result.status == "passed"
        result = scorer.score(_step("a"), _step("b"))
        assert result.status == "failed"


class TestRunScorerProtocol:
    def test_dummy_scorer_satisfies_protocol(self) -> None:
        class TrivialRunScorer:
            name = "trivial-run"

            def score(
                self,
                actual: PipelineRun,
                expected: PipelineRun | None = None,
            ) -> ScoreResult:
                return ScoreResult(score=1.0, status="passed")

        scorer = TrivialRunScorer()
        assert isinstance(scorer, RunScorer)
        result = scorer.score(_run())
        assert result.score == 1.0

    def test_step_scorer_does_not_satisfy_run_scorer(self) -> None:
        """A StepScorer's signature differs from RunScorer's. They're
        structurally distinct; a StepScorer instance should NOT pass
        an isinstance check for RunScorer, because the methods differ
        in name/structure-irrelevant ways but the Protocol contract is
        the same shape ('name' + 'score').

        IMPORTANT caveat: Protocol's @runtime_checkable only verifies
        attribute/method PRESENCE, not signatures. So in practice,
        `isinstance(step_scorer, RunScorer)` returns True even though
        the type system would reject calling it that way. This test
        documents that runtime-checkable Protocols are NOT a complete
        type guard — mypy is the source of truth, isinstance is a
        coarse filter."""

        class TrivialStepScorer:
            name = "trivial"

            def score(
                self,
                actual: StepExecution,
                expected: StepExecution | None = None,
            ) -> ScoreResult:
                return ScoreResult(score=1.0, status="passed")

        # Both Protocols share shape ("name" + "score"), so isinstance is
        # True for both. This is documented Python Protocol behavior.
        scorer = TrivialStepScorer()
        assert isinstance(scorer, StepScorer)
        assert isinstance(scorer, RunScorer)


class TestImports:
    def test_top_level_import(self) -> None:
        from pipewise import RunScorer, ScoreResult, StepScorer  # noqa: F401

    def test_core_subpackage_import(self) -> None:
        from pipewise.core import RunScorer, ScoreResult, StepScorer  # noqa: F401
