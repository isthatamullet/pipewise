"""Tests for the eval-time adapter API.

These tests load the committed sample dataset from ``runs/`` and exercise
``load_run`` + ``default_scorers`` end-to-end. They do NOT make LLM calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pipewise.runner.eval import run_eval

from pipewise_langgraph.adapter import default_scorers, load_run

RUNS_DIR = Path(__file__).parent.parent / "runs"


class TestLoadRun:
    def test_loads_iteration_capture(self):
        run = load_run(RUNS_DIR / "golden-001-iteration.json")
        assert run.run_id == "golden-001-iteration"
        assert run.pipeline_name == "langgraph-react-agent"
        assert run.adapter_name == "pipewise-langgraph"
        step_ids = [s.step_id for s in run.steps]
        assert "agent__1" in step_ids
        assert "agent__2" in step_ids
        assert any(sid.startswith("tools__") for sid in step_ids)

    def test_loads_skipped_capture(self):
        run = load_run(RUNS_DIR / "golden-002-skipped.json")
        skipped_steps = [s for s in run.steps if s.status == "skipped"]
        assert len(skipped_steps) >= 1
        assert any(s.step_id.startswith("tools__") for s in skipped_steps)

    def test_accepts_string_path(self):
        run = load_run(str(RUNS_DIR / "golden-001-iteration.json"))
        assert run.run_id == "golden-001-iteration"

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_run(RUNS_DIR / "does-not-exist.json")


class TestDefaultScorers:
    def test_returns_step_and_run_scorers(self):
        step_scorers, run_scorers = default_scorers()
        assert len(step_scorers) >= 1
        assert len(run_scorers) >= 1

    def test_scorer_names_stable(self):
        step_scorers, run_scorers = default_scorers()
        assert step_scorers[0].name == "langgraph_messages_shape"
        assert run_scorers[0].name == "run_latency_30s"


class TestEndToEndEval:
    def test_iteration_run_passes_all_step_scorers(self):
        run = load_run(RUNS_DIR / "golden-001-iteration.json")
        step_scorers, run_scorers = default_scorers()
        report = run_eval([run], step_scorers, run_scorers, dataset_name="t")
        results_for_run = report.runs[0]
        for step_score in results_for_run.step_scores:
            assert step_score.result.status == "passed", (
                f"step {step_score.step_id} / scorer {step_score.scorer_name} did not pass: "
                f"{step_score.result.reasoning}"
            )
        for run_score in results_for_run.run_scores:
            assert run_score.result.status == "passed"

    def test_skipped_step_results_in_skipped_score(self):
        run = load_run(RUNS_DIR / "golden-002-skipped.json")
        step_scorers, run_scorers = default_scorers()
        report = run_eval([run], step_scorers, run_scorers, dataset_name="t")
        # Find the score for the skipped tools step
        results_for_run = report.runs[0]
        skipped_scores = [
            s
            for s in results_for_run.step_scores
            if s.step_id.startswith("tools__") and s.result.status == "skipped"
        ]
        assert len(skipped_scores) >= 1
