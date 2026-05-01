"""Tests for the eval-time adapter API.

Loads the committed sample dataset from ``runs/`` and exercises ``load_run``
+ ``default_scorers`` end-to-end. No LLM calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pipewise.runner.eval import run_eval

from pipewise_anthropic_quickstarts.adapter import default_scorers, load_run

RUNS_DIR = Path(__file__).parent.parent / "runs"


class TestLoadRun:
    def test_loads_iteration_capture(self):
        run = load_run(RUNS_DIR / "golden-001-iteration.json")
        assert run.run_id == "golden-001-iteration"
        assert run.adapter_name == "pipewise-anthropic-quickstarts"
        step_ids = [s.step_id for s in run.steps]
        assert "agent__1" in step_ids
        assert any(sid.startswith("calculator__") for sid in step_ids)
        assert any(sid.startswith("lookup_country__") for sid in step_ids)

    def test_loads_skipped_capture(self):
        run = load_run(RUNS_DIR / "golden-002-skipped.json")
        # Run B: agent answered without tools → only agent step(s)
        assert all(s.executor == "agent" for s in run.steps)

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
        assert len(run_scorers) >= 2

    def test_scorer_names(self):
        step_scorers, run_scorers = default_scorers()
        step_names = {s.name for s in step_scorers}
        run_names = {s.name for s in run_scorers}
        assert "anthropic_agent_response_shape" in step_names
        assert "run_latency_60s" in run_names
        assert "run_cost_10c" in run_names


class TestEndToEndEval:
    def test_iteration_run_passes_agent_step_scorer(self):
        run = load_run(RUNS_DIR / "golden-001-iteration.json")
        step_scorers, run_scorers = default_scorers()
        report = run_eval([run], step_scorers, run_scorers, dataset_name="t")
        results = report.runs[0]
        # Agent steps should pass the response-shape scorer; tool steps should be skipped.
        agent_scores = [s for s in results.step_scores if s.step_id.startswith("agent__")]
        tool_scores = [s for s in results.step_scores if not s.step_id.startswith("agent__")]
        assert all(s.result.status == "passed" for s in agent_scores)
        assert all(s.result.status == "skipped" for s in tool_scores)

    def test_run_scorers_pass_within_budget(self):
        run = load_run(RUNS_DIR / "golden-001-iteration.json")
        step_scorers, run_scorers = default_scorers()
        report = run_eval([run], step_scorers, run_scorers, dataset_name="t")
        results = report.runs[0]
        for run_score in results.run_scores:
            assert run_score.result.status == "passed", (
                f"run scorer {run_score.scorer_name} did not pass: {run_score.result.reasoning}"
            )

    def test_step_scorer_covers_full_default_iteration_range(self):
        # Regression: scorer scope must cover the agent's DEFAULT_MAX_ITERATIONS
        # (8). Pre-Gemini-fix the scope was agent__1..4 — agent steps 5-8 in
        # longer runs would silently skip validation.
        step_scorers, _ = default_scorers()
        agent_shape = next(s for s in step_scorers if s.name == "anthropic_agent_response_shape")
        scope = set(agent_shape.applies_to_step_ids or ())
        assert {"agent__1", "agent__4", "agent__8"}.issubset(scope)

    def test_skipped_run_passes_all_scopes(self):
        run = load_run(RUNS_DIR / "golden-002-skipped.json")
        step_scorers, run_scorers = default_scorers()
        report = run_eval([run], step_scorers, run_scorers, dataset_name="t")
        results = report.runs[0]
        for step_score in results.step_scores:
            assert step_score.result.status in {"passed", "skipped"}
        for run_score in results.run_scores:
            assert run_score.result.status == "passed"
