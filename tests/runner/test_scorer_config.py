"""Tests for the TOML scorer-config loader (Phase 3 #25)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipewise.runner.scorer_config import ScorerConfigError, load_scorer_config


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


class TestLoadScorerConfig:
    def test_loads_step_scorer_with_kwargs(self, tmp_path: Path) -> None:
        cfg = _write(
            tmp_path / "scorers.toml",
            """
            [scorers.title-exact]
            class = "pipewise.scorers.exact_match.ExactMatchScorer"
            fields = ["title"]
            """,
        )
        step_scorers, run_scorers = load_scorer_config(cfg)

        assert len(step_scorers) == 1
        assert len(run_scorers) == 0
        scorer = step_scorers[0]
        assert scorer.name == "title-exact"

    def test_loads_run_scorer(self, tmp_path: Path) -> None:
        cfg = _write(
            tmp_path / "scorers.toml",
            """
            [scorers.cost-cap]
            class = "pipewise.scorers.budget.CostBudgetScorer"
            budget_usd = 0.50
            """,
        )
        step_scorers, run_scorers = load_scorer_config(cfg)

        assert len(step_scorers) == 0
        assert len(run_scorers) == 1
        assert run_scorers[0].name == "cost-cap"

    def test_loads_mixed_scorers(self, tmp_path: Path) -> None:
        cfg = _write(
            tmp_path / "scorers.toml",
            """
            [scorers.title-exact]
            class = "pipewise.scorers.exact_match.ExactMatchScorer"
            fields = ["title"]

            [scorers.cost-cap]
            class = "pipewise.scorers.budget.CostBudgetScorer"
            budget_usd = 0.50
            """,
        )
        step_scorers, run_scorers = load_scorer_config(cfg)
        assert len(step_scorers) == 1
        assert len(run_scorers) == 1

    def test_empty_toml_yields_empty_lists(self, tmp_path: Path) -> None:
        cfg = _write(tmp_path / "empty.toml", "")
        step_scorers, run_scorers = load_scorer_config(cfg)
        assert step_scorers == []
        assert run_scorers == []

    def test_missing_file_raises_filenotfound(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_scorer_config(tmp_path / "nope.toml")

    def test_missing_class_key_raises(self, tmp_path: Path) -> None:
        cfg = _write(
            tmp_path / "bad.toml",
            """
            [scorers.no-class]
            fields = ["title"]
            """,
        )
        with pytest.raises(ScorerConfigError, match="missing required 'class' key"):
            load_scorer_config(cfg)

    def test_unknown_module_raises(self, tmp_path: Path) -> None:
        cfg = _write(
            tmp_path / "bad.toml",
            """
            [scorers.bad]
            class = "pipewise.scorers.does_not_exist.MissingScorer"
            """,
        )
        with pytest.raises(ScorerConfigError, match="Could not import module"):
            load_scorer_config(cfg)

    def test_unknown_class_in_module_raises(self, tmp_path: Path) -> None:
        cfg = _write(
            tmp_path / "bad.toml",
            """
            [scorers.bad]
            class = "pipewise.scorers.exact_match.NoSuchScorer"
            """,
        )
        with pytest.raises(ScorerConfigError, match="has no attribute 'NoSuchScorer'"):
            load_scorer_config(cfg)

    def test_invalid_constructor_args_raise(self, tmp_path: Path) -> None:
        # ExactMatchScorer requires `fields` to be non-empty.
        cfg = _write(
            tmp_path / "bad.toml",
            """
            [scorers.bad]
            class = "pipewise.scorers.exact_match.ExactMatchScorer"
            fields = []
            """,
        )
        with pytest.raises(ScorerConfigError):
            load_scorer_config(cfg)

    def test_malformed_toml_raises(self, tmp_path: Path) -> None:
        cfg = _write(tmp_path / "bad.toml", "not = valid = toml = [\n")
        with pytest.raises(ScorerConfigError, match="invalid TOML"):
            load_scorer_config(cfg)

    def test_no_class_path_dotted_raises(self, tmp_path: Path) -> None:
        cfg = _write(
            tmp_path / "bad.toml",
            """
            [scorers.bad]
            class = "NoDotsHere"
            """,
        )
        with pytest.raises(ScorerConfigError, match="dotted import path"):
            load_scorer_config(cfg)
