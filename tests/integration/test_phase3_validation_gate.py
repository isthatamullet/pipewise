"""Phase 3 validation gate (issue #27).

Drives `pipewise eval`, `pipewise inspect`, and `pipewise diff` end-to-end
against real FactSpark step data. Reuses the Phase 1 prototype builder
(`_build_factspark_run`) to materialize PipelineRuns from the local
FactSpark articles directory, then exercises the full Phase 3 CLI surface:

1. Build a JSONL dataset of two real runs.
2. Configure 3 Phase 2 scorers via TOML — two RunScorers (cost / latency
   budget, both `on_missing="skip"` because FactSpark doesn't track these
   yet) and one StepScorer (regex against article content).
3. Run `pipewise eval --dataset --adapter --scorers --output-root` and
   verify a real `EvalReport` lands on disk.
4. Run `pipewise inspect` against one of the source PipelineRun JSONs.
5. Run `pipewise eval` a second time with a tighter budget, then
   `pipewise diff` between the two reports and verify regressions surface.

Skips on CI (FactSpark articles dir not present). Pipewise core has zero
runtime dependency on FactSpark per the adapter-pattern rule; this gate
only runs locally.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pipewise import EvalReport, PipelineRun
from pipewise.cli import app
from pipewise.runner.diff import ReportDiff
from tests.integration.test_factspark_validation_gate import (
    FACTSPARK_ARTICLES_DIR,
    SAMPLE_ARTICLE_PREFIX,
    SECOND_ARTICLE_PREFIX,
    _build_factspark_run,
)

pytestmark = pytest.mark.skipif(
    not FACTSPARK_ARTICLES_DIR.exists(),
    reason="FactSpark articles dir not present — Phase 3 gate runs locally only.",
)

cli = CliRunner()

# A minimal adapter module installed once so the CLI's required `--adapter`
# argument resolves. The module satisfies the contract (`load_run` exists)
# but the eval path doesn't actually invoke `load_run` when `--scorers` is
# supplied — the dataset is read directly via `load_dataset`.
_PROTOTYPE_ADAPTER_NAME = "factspark_prototype_phase3_gate"


@pytest.fixture(autouse=True)
def _install_prototype_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType(_PROTOTYPE_ADAPTER_NAME)

    def load_run(_: Path) -> PipelineRun:
        return _build_factspark_run(SAMPLE_ARTICLE_PREFIX)

    module.load_run = load_run  # type: ignore[attr-defined]
    sys.modules[_PROTOTYPE_ADAPTER_NAME] = module
    monkeypatch.setitem(sys.modules, _PROTOTYPE_ADAPTER_NAME, module)


def _write_golden_dataset(path: Path) -> list[PipelineRun]:
    """Materialize 2 real FactSpark runs and write them as a JSONL dataset."""
    runs = [_build_factspark_run(SAMPLE_ARTICLE_PREFIX)]
    if (FACTSPARK_ARTICLES_DIR / f"{SECOND_ARTICLE_PREFIX}_step1.json").exists():
        runs.append(_build_factspark_run(SECOND_ARTICLE_PREFIX))
    path.write_text("\n".join(r.model_dump_json() for r in runs))
    return runs


def _scorer_config(tmp_path: Path, *, budget_usd: float = 1.0) -> Path:
    """Write a TOML scorer config exercising 3 Phase 2 scorers."""
    config = tmp_path / "scorers.toml"
    config.write_text(
        f"""
        [scorers.cost-cap]
        class = "pipewise.scorers.budget.CostBudgetScorer"
        budget_usd = {budget_usd}
        on_missing = "skip"

        [scorers.latency-cap]
        class = "pipewise.scorers.budget.LatencyBudgetScorer"
        budget_ms = 60000
        on_missing = "skip"

        [scorers.article-has-content]
        class = "pipewise.scorers.regex.RegexScorer"
        field = "full_article_content"
        pattern = ".{{100,}}"
        """
    )
    return config


def test_eval_writes_real_evalreport_against_factspark_data(tmp_path: Path) -> None:
    dataset = tmp_path / "factspark-golden.jsonl"
    runs = _write_golden_dataset(dataset)
    config = _scorer_config(tmp_path)
    output_root = tmp_path / "reports"

    result = cli.invoke(
        app,
        [
            "eval",
            "--dataset",
            str(dataset),
            "--adapter",
            _PROTOTYPE_ADAPTER_NAME,
            "--scorers",
            str(config),
            "--output-root",
            str(output_root),
            "--dataset-name",
            "factspark",
        ],
    )

    # Eval produces both pass-results (cost/latency skipped → passing,
    # regex passes on step 1) and fail-results (regex fails on steps 2-7
    # because they don't have `full_article_content`). Exit 1 because
    # there are failing scorers — that's the headline-command contract.
    assert result.exit_code == 1, result.stdout

    # The summary line names the dataset, scorer counts, pass/fail counts, and report path.
    assert "Evaluated" in result.stdout
    assert f"{len(runs)} run(s)" in result.stdout
    assert "1 step scorer(s) + 2 run scorer(s)" in result.stdout
    assert "Report:" in result.stdout

    # Exactly one timestamped subdir; the report.json round-trips.
    subdirs = list(output_root.iterdir())
    assert len(subdirs) == 1
    report_dir = subdirs[0]
    assert report_dir.name.endswith("_factspark")
    report_path = report_dir / "report.json"
    report = EvalReport.model_validate_json(report_path.read_text())

    assert report.dataset_name == "factspark"
    assert len(report.runs) == len(runs)
    assert report.scorer_names == ["article-has-content", "cost-cap", "latency-cap"]

    # FactSpark's pipeline propagates `full_article_content` through steps
    # 1-6; step 7 (Gemini verifier) has a different schema and does not
    # carry that field. So the regex passes on 6 steps and fails on 1.
    for run_result in report.runs:
        step_passes = sum(1 for e in run_result.step_scores if e.result.status == "passed")
        step_fails = sum(1 for e in run_result.step_scores if e.result.status != "passed")
        assert step_passes == 6, (
            "regex should pass on steps 1-6 (which propagate full_article_content)"
        )
        assert step_fails == 1, "regex should fail on step 7 (different schema)"
        # Both budget scorers use on_missing="skip" → emit "skipped" (no signal).
        assert all(e.result.status == "skipped" for e in run_result.run_scores)


def test_inspect_displays_a_real_factspark_run_cleanly(tmp_path: Path) -> None:
    run = _build_factspark_run(SAMPLE_ARTICLE_PREFIX)
    run_path = tmp_path / "run.json"
    run_path.write_text(run.model_dump_json())

    result = cli.invoke(app, ["inspect", str(run_path)])

    assert result.exit_code == 0, result.stdout
    # Identifying fields surface in the formatted output.
    assert SAMPLE_ARTICLE_PREFIX in result.stdout
    assert "factspark" in result.stdout
    assert "Steps (7)" in result.stdout
    # Step 7 is the Gemini verifier.
    assert "verify_claims" in result.stdout


def test_diff_surfaces_regressions_between_two_real_eval_reports(tmp_path: Path) -> None:
    # Run 1: loose budget. Run 2: zero budget. Both with on_missing="skip",
    # so the budget scorers pass in both runs anyway — but the per-scorer
    # `name` is identical across runs ("cost-cap"), so the diff is empty
    # for those entries. To force a regression that diff can detect, we
    # change the regex scorer to look for a field that exists in run A
    # (full_article_content on step 1) but use a different field/pattern
    # in run B that fails for everyone.
    dataset = tmp_path / "factspark-golden.jsonl"
    _write_golden_dataset(dataset)
    output_root = tmp_path / "reports"

    config_a = tmp_path / "scorers_a.toml"
    config_a.write_text(
        """
        [scorers.article-has-content]
        class = "pipewise.scorers.regex.RegexScorer"
        field = "full_article_content"
        pattern = ".{100,}"
        """
    )

    config_b = tmp_path / "scorers_b.toml"
    config_b.write_text(
        """
        [scorers.article-has-content]
        class = "pipewise.scorers.regex.RegexScorer"
        field = "full_article_content"
        pattern = "this-string-will-never-match-anywhere"
        """
    )

    # Run A: passes regex on step 1.
    result_a = cli.invoke(
        app,
        [
            "eval",
            "--dataset",
            str(dataset),
            "--adapter",
            _PROTOTYPE_ADAPTER_NAME,
            "--scorers",
            str(config_a),
            "--output-root",
            str(output_root),
            "--dataset-name",
            "factspark-a",
        ],
    )
    # Even with all-passing step 1, steps 2-7 still fail for the regex
    # scorer (field missing) — so the eval exits 1.
    assert result_a.exit_code == 1
    report_a_path = (
        next(p for p in output_root.iterdir() if "factspark-a" in p.name) / "report.json"
    )

    result_b = cli.invoke(
        app,
        [
            "eval",
            "--dataset",
            str(dataset),
            "--adapter",
            _PROTOTYPE_ADAPTER_NAME,
            "--scorers",
            str(config_b),
            "--output-root",
            str(output_root),
            "--dataset-name",
            "factspark-b",
        ],
    )
    assert result_b.exit_code == 1
    report_b_path = (
        next(p for p in output_root.iterdir() if "factspark-b" in p.name) / "report.json"
    )

    # Diff: step 1's regex regressed (was passing in A, now failing in B).
    result_diff = cli.invoke(
        app, ["diff", str(report_a_path), str(report_b_path), "--format", "json"]
    )

    # Regressions present → exit 1.
    assert result_diff.exit_code == 1, result_diff.stdout

    diff = ReportDiff.model_validate_json(result_diff.stdout)
    assert diff.has_regressions()
    # 6 regressions per run (steps 1-6, where the regex was passing in A
    # and now fails in B because the pattern doesn't match anywhere).
    # Step 7 was already failing in A (no `full_article_content`), so it
    # stays failing in B — that's not a regression.
    assert all(e.passed_a and not e.passed_b for e in diff.regressions)
    regressed_step_ids = {e.step_id for e in diff.regressions}
    assert "analyze" in regressed_step_ids  # step 1
    assert "verify_claims" not in regressed_step_ids  # step 7 was already failing
    # No improvements (regex got strictly worse on previously-passing steps).
    assert diff.improvements == []


def test_diff_in_text_format_renders_summary_line(tmp_path: Path) -> None:
    """Spot-check that the human-readable diff render works on real data."""
    dataset = tmp_path / "factspark-golden.jsonl"
    _write_golden_dataset(dataset)
    output_root = tmp_path / "reports"
    config = _scorer_config(tmp_path)

    cli.invoke(
        app,
        [
            "eval",
            "--dataset",
            str(dataset),
            "--adapter",
            _PROTOTYPE_ADAPTER_NAME,
            "--scorers",
            str(config),
            "--output-root",
            str(output_root),
            "--dataset-name",
            "factspark",
        ],
    )
    report_dir = next(output_root.iterdir())
    report_path = report_dir / "report.json"

    # Diff a report against itself — every entry is unchanged.
    result = cli.invoke(app, ["diff", str(report_path), str(report_path)])
    assert result.exit_code == 0
    assert "Summary:" in result.stdout
    assert "0 regressed" in result.stdout
