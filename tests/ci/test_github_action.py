"""Tests for `pipewise.ci.github_action.render_pr_comment` (#36)."""

from __future__ import annotations

from datetime import UTC, datetime

from pipewise import (
    EvalReport,
    RunEvalResult,
    RunScoreEntry,
    ScoreResult,
    StepScoreEntry,
)
from pipewise.ci import render_pr_comment

NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=UTC)


def _result(score: float, passed: bool) -> ScoreResult:
    return ScoreResult(score=score, passed=passed)


def _step_entry(step_id: str, scorer_name: str, score: float, passed: bool) -> StepScoreEntry:
    return StepScoreEntry(step_id=step_id, scorer_name=scorer_name, result=_result(score, passed))


def _run_entry(scorer_name: str, score: float, passed: bool) -> RunScoreEntry:
    return RunScoreEntry(scorer_name=scorer_name, result=_result(score, passed))


def _run(
    *,
    run_id: str = "run_1",
    step_scores: list[StepScoreEntry] | None = None,
    run_scores: list[RunScoreEntry] | None = None,
) -> RunEvalResult:
    return RunEvalResult(
        run_id=run_id,
        pipeline_name="factspark",
        adapter_name="factspark_pipewise",
        adapter_version="0.0.1",
        step_scores=step_scores or [],
        run_scores=run_scores or [],
    )


def _report(
    *,
    runs: list[RunEvalResult],
    dataset_name: str | None = "golden.jsonl",
) -> EvalReport:
    return EvalReport(
        report_id="test-report",
        generated_at=NOW,
        pipewise_version="0.0.1",
        dataset_name=dataset_name,
        scorer_names=["any"],
        runs=runs,
    )


# ─── Reference state A: passing, no change vs main ───────────────────────────


class TestPassingNoChange:
    def _identical_pair(self) -> tuple[EvalReport, EvalReport]:
        run_steps = [
            _step_entry("extract", "ExactMatch", 0.94, True),
            _step_entry("analyze", "LlmJudge", 0.88, True),
            _step_entry("format", "Regex", 1.00, True),
        ]
        baseline = _report(runs=[_run(run_id="r1", step_scores=run_steps)])
        report = _report(runs=[_run(run_id="r1", step_scores=list(run_steps))])
        return baseline, report

    def test_verdict_says_no_change(self) -> None:
        baseline, report = self._identical_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="abc1234"
        )
        assert "✅ All scorers passing · no change vs main" in out

    def test_delta_column_shows_dash_for_unchanged(self) -> None:
        baseline, report = self._identical_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="abc1234"
        )
        # Three rollup rows; each Δ cell should be the em-dash placeholder.
        # Match `| — |` at line ends (the trailing pipe of the Δ column).
        assert out.count("| — |") >= 3

    def test_counts_show_zero_regressions_zero_improvements(self) -> None:
        baseline, report = self._identical_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="abc1234"
        )
        assert "**Regressions:** 0 🔴" in out
        assert "**Improvements:** 0 🟢" in out
        assert "**Unchanged:** 3" in out

    def test_no_newly_failing_section_when_no_regressions(self) -> None:
        baseline, report = self._identical_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="abc1234"
        )
        assert "Newly failing checks" not in out


# ─── Reference state B: passing with improvements ────────────────────────────


class TestPassingWithImprovements:
    def _improved_pair(self) -> tuple[EvalReport, EvalReport]:
        # Two scorers improved by flipping fail→pass; one unchanged.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("extract", "ExactMatch", 0.40, False),
                        _step_entry("analyze", "LlmJudge", 0.45, False),
                        _step_entry("format", "Regex", 1.00, True),
                    ],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("extract", "ExactMatch", 0.97, True),
                        _step_entry("analyze", "LlmJudge", 0.91, True),
                        _step_entry("format", "Regex", 1.00, True),
                    ],
                )
            ]
        )
        return baseline, report

    def test_verdict_announces_improvements(self) -> None:
        baseline, report = self._improved_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="def5678"
        )
        assert "✅ All scorers passing · 2 improvements 🟢" in out

    def test_delta_column_shows_signed_positives(self) -> None:
        baseline, report = self._improved_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="def5678"
        )
        assert "+0.57 🟢" in out  # 0.97 - 0.40
        assert "+0.46 🟢" in out  # 0.91 - 0.45

    def test_counts_show_two_improvements_one_unchanged(self) -> None:
        baseline, report = self._improved_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="def5678"
        )
        assert "**Regressions:** 0 🔴" in out
        assert "**Improvements:** 2 🟢" in out
        assert "**Unchanged:** 1" in out


# ─── Reference state C: regressing with newly-failing checks ─────────────────


class TestRegressing:
    def _regressed_pair(self) -> tuple[EvalReport, EvalReport]:
        # One true regression (pass→fail) + one score_delta with negative delta.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("extract", "ExactMatch", 0.94, True),
                        _step_entry("analyze", "LlmJudge", 0.88, True),
                        _step_entry("format", "Regex", 1.00, True),
                    ],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("extract", "ExactMatch", 0.81, True),
                        _step_entry("analyze", "LlmJudge", 0.85, True),
                        _step_entry("format", "Regex", 0.45, False),
                    ],
                )
            ]
        )
        return baseline, report

    def test_verdict_announces_regressions(self) -> None:
        baseline, report = self._regressed_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="9abc012"
        )
        assert out.startswith("<!-- pipewise-eval-report:factspark -->")
        assert "❌ 1 regression · was passing on main, failing here" in out

    def test_delta_column_shows_signed_negatives_with_red_emoji(self) -> None:
        baseline, report = self._regressed_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="9abc012"
        )
        assert "-0.55 🔴" in out  # 0.45 - 1.00 (the regression)
        assert "-0.13 🔴" in out  # 0.81 - 0.94 (score delta)
        assert "-0.03 🔴" in out  # 0.85 - 0.88 (score delta)

    def test_newly_failing_section_lists_regression_with_run_id(self) -> None:
        baseline, report = self._regressed_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="9abc012"
        )
        assert "<details><summary><b>Newly failing checks (1)</b></summary>" in out
        assert "`Regex` × `format`" in out
        assert "run `r1`" in out
        assert "passed → failed" in out

    def test_counts_show_one_regression(self) -> None:
        baseline, report = self._regressed_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="9abc012"
        )
        assert "**Regressions:** 1 🔴" in out
        assert "**Improvements:** 0 🟢" in out


# ─── Missing baseline ────────────────────────────────────────────────────────


class TestNoBaseline:
    def test_verdict_announces_no_baseline(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.94, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="factspark", short_sha="abc1234")
        assert "🆕 1 run · 1/1 scorers passing · no baseline" in out

    def test_no_counts_row_when_baseline_missing(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.94, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="factspark", short_sha="abc1234")
        # Counts row only renders with a baseline.
        assert "**Regressions:**" not in out
        assert "**Improvements:**" not in out

    def test_delta_column_shows_dash_when_baseline_missing(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.94, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="factspark", short_sha="abc1234")
        # Main column should be `—` and Δ column should be `—`.
        assert "| — | 0.94 | — |" in out


# ─── Structural / cross-cutting checks ───────────────────────────────────────


class TestStructure:
    def test_sticky_marker_is_first_line_and_keyed_by_adapter_name(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 1.0, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="my-adapter", short_sha="abc")
        assert out.startswith("<!-- pipewise-eval-report:my-adapter -->\n")

    def test_h2_header_includes_adapter_name(self) -> None:
        report = _report(runs=[_run(run_id="r1")])
        out = render_pr_comment(report, adapter_name="resume_tailor", short_sha="abc")
        assert "## Pipewise eval report — resume_tailor" in out

    def test_short_sha_appears_in_footer(self) -> None:
        report = _report(runs=[_run(run_id="r1")])
        out = render_pr_comment(report, adapter_name="factspark", short_sha="deadbee")
        assert "<sub>Updated for `deadbee` ·" in out

    def test_run_level_scorers_appear_with_run_level_label(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    run_scores=[_run_entry("CostBudget", 1.0, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="factspark", short_sha="abc")
        assert "`CostBudget` (run-level)" in out

    def test_rollup_header_uses_right_aligned_separators(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 1.0, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="factspark", short_sha="abc")
        # Right-aligned numeric columns per the locked design spec.
        assert "| :--- | ---: | ---: | ---: |" in out

    def test_full_report_details_lists_each_case(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="run_a",
                    step_scores=[
                        _step_entry("s1", "ExactMatch", 0.9, True),
                        _step_entry("s2", "Regex", 0.5, False),
                    ],
                ),
                _run(
                    run_id="run_b",
                    step_scores=[
                        _step_entry("s1", "ExactMatch", 1.0, True),
                    ],
                ),
            ]
        )
        out = render_pr_comment(report, adapter_name="factspark", short_sha="abc")
        assert "<summary>Full report (2 runs · dataset: golden.jsonl)</summary>" in out
        assert "`run_a` | `s1` | `ExactMatch`" in out
        assert "`run_a` | `s2` | `Regex`" in out
        assert "`run_b` | `s1` | `ExactMatch`" in out
        # Pass/fail emoji per row.
        assert " ✅ |" in out
        assert " ❌ |" in out

    def test_output_ends_with_single_trailing_newline(self) -> None:
        report = _report(runs=[_run(run_id="r1")])
        out = render_pr_comment(report, adapter_name="factspark", short_sha="abc")
        assert out.endswith("\n")
        assert not out.endswith("\n\n")

    def test_dataset_name_falls_back_to_dash_when_missing(self) -> None:
        report = _report(runs=[_run(run_id="r1")], dataset_name=None)
        out = render_pr_comment(report, adapter_name="factspark", short_sha="abc")
        assert "dataset: —" in out

    def test_empty_report_renders_gracefully(self) -> None:
        report = _report(runs=[])
        out = render_pr_comment(report, adapter_name="factspark", short_sha="abc")
        # No table rows but header + placeholder still renders.
        assert "_No scorer results in this report._" in out
        assert "_No runs in this report._" in out


# ─── Failing-but-not-regressed (warning) state ───────────────────────────────


class TestFailingButNoRegressions:
    def test_verdict_warns_when_failing_already_failing(self) -> None:
        # Scorer was already failing on main and is still failing here.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.20, False)],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.20, False)],
                )
            ]
        )
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="factspark", short_sha="abc"
        )
        assert "⚠️ 1 failing scorer · no regressions vs main" in out
