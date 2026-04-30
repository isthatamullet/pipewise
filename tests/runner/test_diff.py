"""Tests for `pipewise diff` and `compute_diff` (#26)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from pipewise import (
    EvalReport,
    RunEvalResult,
    RunScoreEntry,
    ScoreResult,
    StepScoreEntry,
)
from pipewise.cli import app
from pipewise.runner.diff import ReportDiff, compute_diff, format_diff

NOW = datetime(2026, 4, 27, 9, 15, 0, tzinfo=UTC)
runner = CliRunner()


def _result(score: float, passed: bool) -> ScoreResult:
    return ScoreResult(status="passed" if passed else "failed", score=score)


def _report(
    *,
    runs: list[RunEvalResult],
    report_id: str = "test",
    dataset_name: str | None = "ds",
) -> EvalReport:
    return EvalReport(
        report_id=report_id,
        generated_at=NOW,
        pipewise_version="0.0.1",
        dataset_name=dataset_name,
        scorer_names=["any"],
        runs=runs,
    )


def _run(
    *,
    run_id: str = "run_1",
    step_scores: list[StepScoreEntry] | None = None,
    run_scores: list[RunScoreEntry] | None = None,
) -> RunEvalResult:
    return RunEvalResult(
        run_id=run_id,
        pipeline_name="fake",
        adapter_name="fake-adapter",
        adapter_version="0.0.1",
        step_scores=step_scores or [],
        run_scores=run_scores or [],
    )


class TestComputeDiff:
    def test_empty_reports_yield_empty_diff(self) -> None:
        diff = compute_diff(_report(runs=[]), _report(runs=[]))
        assert diff.total_changes() == 0
        assert not diff.has_regressions()

    def test_run_only_in_a_listed_in_runs_a_only(self) -> None:
        a = _report(runs=[_run(run_id="run_1"), _run(run_id="run_2")])
        b = _report(runs=[_run(run_id="run_1")])
        diff = compute_diff(a, b)
        assert diff.runs_a_only == ["run_2"]
        assert diff.runs_b_only == []

    def test_run_only_in_b_listed_in_runs_b_only(self) -> None:
        a = _report(runs=[_run(run_id="run_1")])
        b = _report(runs=[_run(run_id="run_1"), _run(run_id="run_3")])
        diff = compute_diff(a, b)
        assert diff.runs_b_only == ["run_3"]

    def test_passing_to_failing_is_regression(self) -> None:
        a = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(1.0, True))])]
        )
        b = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(0.0, False))])]
        )
        diff = compute_diff(a, b)
        assert len(diff.regressions) == 1
        entry = diff.regressions[0]
        assert entry.run_id == "run_1"
        assert entry.step_id is None
        assert entry.scorer_name == "s"
        assert entry.passed_a is True
        assert entry.passed_b is False
        assert diff.has_regressions()

    def test_failing_to_passing_is_improvement(self) -> None:
        a = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(0.0, False))])]
        )
        b = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(1.0, True))])]
        )
        diff = compute_diff(a, b)
        assert len(diff.improvements) == 1
        assert not diff.has_regressions()

    def test_score_change_with_same_pass_status_is_score_delta(self) -> None:
        a = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(0.95, True))])]
        )
        b = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(0.92, True))])]
        )
        diff = compute_diff(a, b)
        assert len(diff.score_deltas) == 1
        entry = diff.score_deltas[0]
        assert abs(entry.delta - (-0.03)) < 1e-9

    def test_unchanged_entry_appears_in_no_diff_section(self) -> None:
        same = [RunScoreEntry(scorer_name="s", result=_result(1.0, True))]
        a = _report(runs=[_run(run_scores=same)])
        b = _report(runs=[_run(run_scores=same)])
        diff = compute_diff(a, b)
        assert diff.total_changes() == 0

    def test_step_scorer_diff_keyed_by_step_id(self) -> None:
        a_steps = [
            StepScoreEntry(step_id="s1", scorer_name="x", result=_result(1.0, True)),
            StepScoreEntry(step_id="s2", scorer_name="x", result=_result(1.0, True)),
        ]
        b_steps = [
            StepScoreEntry(step_id="s1", scorer_name="x", result=_result(1.0, True)),
            StepScoreEntry(step_id="s2", scorer_name="x", result=_result(0.0, False)),
        ]
        diff = compute_diff(
            _report(runs=[_run(step_scores=a_steps)]),
            _report(runs=[_run(step_scores=b_steps)]),
        )
        assert len(diff.regressions) == 1
        assert diff.regressions[0].step_id == "s2"

    def test_absent_in_b_when_scorer_dropped(self) -> None:
        a_steps = [StepScoreEntry(step_id="s1", scorer_name="x", result=_result(1.0, True))]
        diff = compute_diff(
            _report(runs=[_run(step_scores=a_steps)]),
            _report(runs=[_run()]),
        )
        assert len(diff.absent_in_b) == 1
        assert diff.absent_in_b[0].scorer_name == "x"

    def test_absent_in_a_when_scorer_added(self) -> None:
        b_steps = [StepScoreEntry(step_id="s1", scorer_name="x", result=_result(1.0, True))]
        diff = compute_diff(
            _report(runs=[_run()]),
            _report(runs=[_run(step_scores=b_steps)]),
        )
        assert len(diff.absent_in_a) == 1

    def test_mixed_step_and_run_level_entries_sort_without_typeerror(self) -> None:
        # Regression guard: `_ScoreEntryKey.step_id` is `str | None`, and an
        # earlier `compute_diff` implementation sorted the union of keys
        # directly — Python can't compare None to str, which crashed when a
        # run had both step-level and run-level scorer entries.
        a = _report(
            runs=[
                _run(
                    step_scores=[
                        StepScoreEntry(
                            step_id="s1", scorer_name="step-x", result=_result(1.0, True)
                        )
                    ],
                    run_scores=[RunScoreEntry(scorer_name="run-y", result=_result(1.0, True))],
                )
            ]
        )
        b = _report(
            runs=[
                _run(
                    step_scores=[
                        StepScoreEntry(
                            step_id="s1", scorer_name="step-x", result=_result(0.0, False)
                        )
                    ],
                    run_scores=[RunScoreEntry(scorer_name="run-y", result=_result(0.0, False))],
                )
            ]
        )
        diff = compute_diff(a, b)
        assert len(diff.regressions) == 2


class TestFormatDiff:
    def test_renders_summary_line(self) -> None:
        out = format_diff(ReportDiff())
        assert "Summary:" in out

    def test_includes_regression_section_when_present(self) -> None:
        a = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(1.0, True))])]
        )
        b = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(0.0, False))])]
        )
        out = format_diff(compute_diff(a, b))
        assert "Newly failing" in out
        assert "run_1" in out


class TestDiffCommand:
    def _write(self, path: Path, report: EvalReport) -> None:
        path.write_text(report.model_dump_json())

    def test_no_regressions_exits_zero(self, tmp_path: Path) -> None:
        same = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(1.0, True))])]
        )
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        self._write(a, same)
        self._write(b, same)

        result = runner.invoke(app, ["diff", str(a), str(b)])
        assert result.exit_code == 0
        assert "Summary:" in result.stdout

    def test_regressions_exit_nonzero(self, tmp_path: Path) -> None:
        a = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(1.0, True))])]
        )
        b = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(0.0, False))])]
        )
        a_path = tmp_path / "a.json"
        b_path = tmp_path / "b.json"
        self._write(a_path, a)
        self._write(b_path, b)

        result = runner.invoke(app, ["diff", str(a_path), str(b_path)])
        assert result.exit_code == 1
        assert "Newly failing" in result.stdout

    def test_format_json_emits_valid_diff_json(self, tmp_path: Path) -> None:
        report = _report(
            runs=[_run(run_scores=[RunScoreEntry(scorer_name="s", result=_result(1.0, True))])]
        )
        a_path = tmp_path / "a.json"
        b_path = tmp_path / "b.json"
        self._write(a_path, report)
        self._write(b_path, report)

        result = runner.invoke(app, ["diff", str(a_path), str(b_path), "--format", "json"])
        assert result.exit_code == 0
        # The trailing line is a newline from typer.echo; everything before is JSON.
        diff = ReportDiff.model_validate_json(result.stdout)
        assert diff.total_changes() == 0

    def test_missing_file_exits_with_clear_error(self, tmp_path: Path) -> None:
        report = _report(runs=[])
        a_path = tmp_path / "a.json"
        self._write(a_path, report)
        result = runner.invoke(app, ["diff", str(a_path), str(tmp_path / "nope.json")])
        assert result.exit_code == 2
        combined = result.stdout + (result.stderr or "")
        assert "file not found" in combined.lower()
