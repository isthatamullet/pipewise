"""Tests for `EvalReport` + `RunEvalResult` + `StepScoreEntry` / `RunScoreEntry`."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pipewise import (
    EvalReport,
    RunEvalResult,
    RunScoreEntry,
    ScoreResult,
    StepScoreEntry,
)

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _passing(reasoning: str = "") -> ScoreResult:
    return ScoreResult(score=1.0, passed=True, reasoning=reasoning or None)


def _failing(reasoning: str = "") -> ScoreResult:
    return ScoreResult(score=0.0, passed=False, reasoning=reasoning or None)


class TestEntries:
    """`StepScoreEntry` and `RunScoreEntry` — the inner records."""

    def test_step_entry_minimal(self) -> None:
        entry = StepScoreEntry(
            step_id="analyze",
            scorer_name="exact_match",
            result=_passing(),
        )
        assert entry.step_id == "analyze"
        assert entry.result.passed is True

    def test_run_entry_minimal(self) -> None:
        entry = RunScoreEntry(
            scorer_name="cost_budget",
            result=_passing("$0.02 < $0.05 budget"),
        )
        assert entry.scorer_name == "cost_budget"

    @pytest.mark.parametrize(
        "field",
        [("step_id"), ("scorer_name")],
    )
    def test_step_entry_empty_required_string_rejected(self, field: str) -> None:
        kwargs: dict[str, object] = {
            "step_id": "x",
            "scorer_name": "x",
            "result": _passing(),
        }
        kwargs[field] = ""
        with pytest.raises(ValidationError):
            StepScoreEntry(**kwargs)  # type: ignore[arg-type]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepScoreEntry(
                step_id="x",
                scorer_name="x",
                result=_passing(),
                unknown="value",  # type: ignore[call-arg]
            )


class TestRunEvalResult:
    def _result(self, **overrides: object) -> RunEvalResult:
        defaults: dict[str, object] = {
            "run_id": "r1",
            "pipeline_name": "example",
            "adapter_name": "example-adapter",
            "adapter_version": "0.1.0",
        }
        defaults.update(overrides)
        return RunEvalResult(**defaults)  # type: ignore[arg-type]

    def test_minimal_valid(self) -> None:
        result = self._result()
        assert result.step_scores == []
        assert result.run_scores == []
        assert result.pipeline_version is None

    def test_all_results_concatenates_step_and_run_scores(self) -> None:
        result = self._result(
            step_scores=[
                StepScoreEntry(step_id="s1", scorer_name="exact", result=_passing()),
                StepScoreEntry(step_id="s2", scorer_name="exact", result=_failing()),
            ],
            run_scores=[
                RunScoreEntry(scorer_name="cost_budget", result=_passing()),
            ],
        )
        all_results = result.all_results()
        assert len(all_results) == 3
        # Step scores come first, in order, then run scores.
        assert all_results[0].passed is True
        assert all_results[1].passed is False
        assert all_results[2].passed is True

    def test_all_passed_when_everything_passes(self) -> None:
        result = self._result(
            step_scores=[
                StepScoreEntry(step_id="s1", scorer_name="exact", result=_passing()),
            ],
            run_scores=[
                RunScoreEntry(scorer_name="cost_budget", result=_passing()),
            ],
        )
        assert result.all_passed() is True

    def test_all_passed_false_when_any_fails(self) -> None:
        result = self._result(
            step_scores=[
                StepScoreEntry(step_id="s1", scorer_name="exact", result=_passing()),
                StepScoreEntry(step_id="s2", scorer_name="exact", result=_failing()),
            ],
        )
        assert result.all_passed() is False

    def test_all_passed_vacuously_true_when_no_scores(self) -> None:
        # Documented behavior: a run with zero scorers is "passing" by Python's
        # all([]) semantics. Consumers wanting "untested" semantics should
        # check len(all_results()) first.
        result = self._result()
        assert result.all_passed() is True
        assert len(result.all_results()) == 0


class TestEvalReport:
    def _report(self, **overrides: object) -> EvalReport:
        defaults: dict[str, object] = {
            "report_id": "report_2026_04_27",
            "generated_at": NOW,
            "pipewise_version": "0.0.1",
        }
        defaults.update(overrides)
        return EvalReport(**defaults)  # type: ignore[arg-type]

    def _run_result(self, run_id: str, *entries: StepScoreEntry | RunScoreEntry) -> RunEvalResult:
        step_scores = [e for e in entries if isinstance(e, StepScoreEntry)]
        run_scores = [e for e in entries if isinstance(e, RunScoreEntry)]
        return RunEvalResult(
            run_id=run_id,
            pipeline_name="example",
            adapter_name="example-adapter",
            adapter_version="0.1.0",
            step_scores=step_scores,
            run_scores=run_scores,
        )

    def test_minimal_valid(self) -> None:
        report = self._report()
        assert report.runs == []
        assert report.scorer_names == []
        assert report.dataset_name is None
        assert report.metadata == {}

    def test_total_score_count_across_runs(self) -> None:
        report = self._report(
            runs=[
                self._run_result(
                    "r1",
                    StepScoreEntry(step_id="s1", scorer_name="exact", result=_passing()),
                    StepScoreEntry(step_id="s2", scorer_name="exact", result=_passing()),
                    RunScoreEntry(scorer_name="cost_budget", result=_passing()),
                ),
                self._run_result(
                    "r2",
                    StepScoreEntry(step_id="s1", scorer_name="exact", result=_failing()),
                ),
            ],
        )
        assert report.total_score_count() == 4
        assert report.passing_score_count() == 3
        assert report.failing_score_count() == 1

    def test_passing_and_failing_run_ids(self) -> None:
        report = self._report(
            runs=[
                self._run_result(
                    "r_pass_1",
                    StepScoreEntry(step_id="s", scorer_name="x", result=_passing()),
                ),
                self._run_result(
                    "r_pass_2",
                    RunScoreEntry(scorer_name="cost", result=_passing()),
                ),
                self._run_result(
                    "r_fail",
                    StepScoreEntry(step_id="s", scorer_name="x", result=_passing()),
                    StepScoreEntry(step_id="t", scorer_name="x", result=_failing()),
                ),
                self._run_result("r_empty"),  # vacuously passing
            ],
        )
        assert report.passing_run_ids() == ["r_pass_1", "r_pass_2", "r_empty"]
        assert report.failing_run_ids() == ["r_fail"]

    def test_find_run(self) -> None:
        report = self._report(runs=[self._run_result("r1"), self._run_result("r2")])
        found = report.find_run("r2")
        assert found is not None
        assert found.run_id == "r2"
        assert report.find_run("nonexistent") is None

    def test_find_step_scorer_result(self) -> None:
        passing_step = _passing("3-of-5 verified")
        report = self._report(
            runs=[
                self._run_result(
                    "r1",
                    StepScoreEntry(step_id="analyze", scorer_name="exact", result=passing_step),
                    StepScoreEntry(step_id="analyze", scorer_name="schema", result=_passing()),
                    StepScoreEntry(step_id="enhance", scorer_name="exact", result=_failing()),
                ),
            ],
        )
        # Step + scorer match
        result = report.find_scorer_result("r1", "exact", step_id="analyze")
        assert result is not None
        assert result.reasoning == "3-of-5 verified"

        # Step + different scorer
        assert report.find_scorer_result("r1", "schema", step_id="analyze") is not None

        # Non-matching scorer name on a real step
        assert report.find_scorer_result("r1", "missing", step_id="analyze") is None

        # Non-matching step_id
        assert report.find_scorer_result("r1", "exact", step_id="missing") is None

    def test_find_run_scorer_result(self) -> None:
        report = self._report(
            runs=[
                self._run_result(
                    "r1",
                    RunScoreEntry(scorer_name="cost_budget", result=_passing("$0.02 < $0.05")),
                ),
            ],
        )
        # Run-level lookup (no step_id)
        result = report.find_scorer_result("r1", "cost_budget")
        assert result is not None
        assert "$0.02" in (result.reasoning or "")

        # Run-level lookup for non-existent scorer
        assert report.find_scorer_result("r1", "missing") is None

    def test_find_scorer_result_for_unknown_run(self) -> None:
        report = self._report(runs=[self._run_result("r1")])
        assert report.find_scorer_result("nonexistent", "any") is None

    def test_round_trip_json(self) -> None:
        report = self._report(
            dataset_name="factspark-golden-v1",
            scorer_names=["exact_match", "cost_budget"],
            runs=[
                self._run_result(
                    "r1",
                    StepScoreEntry(
                        step_id="analyze",
                        scorer_name="exact_match",
                        result=_passing("ok"),
                    ),
                    RunScoreEntry(scorer_name="cost_budget", result=_passing("under budget")),
                ),
            ],
            metadata={"git_sha": "abc123"},
        )
        serialized = report.model_dump_json()
        restored = EvalReport.model_validate_json(serialized)
        assert restored == report
        assert restored.metadata["git_sha"] == "abc123"

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._report(unknown_field="value")

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._report(generated_at=datetime(2026, 4, 27, 12, 0, 0))

    @pytest.mark.parametrize(
        "field",
        ["report_id", "pipewise_version"],
    )
    def test_empty_required_string_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError):
            self._report(**{field: ""})


class TestImports:
    def test_top_level_import(self) -> None:
        from pipewise import (  # noqa: F401
            EvalReport,
            RunEvalResult,
            RunScoreEntry,
            StepScoreEntry,
        )

    def test_core_subpackage_import(self) -> None:
        from pipewise.core import (  # noqa: F401
            EvalReport,
            RunEvalResult,
            RunScoreEntry,
            StepScoreEntry,
        )
