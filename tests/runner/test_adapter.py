"""Tests for the adapter resolver (Phase 3 #21)."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipewise import PipelineRun
from pipewise.runner.adapter import (
    AdapterError,
    resolve_adapter,
    resolve_default_scorers,
)

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _make_run() -> PipelineRun:
    return PipelineRun(
        run_id="run_1",
        pipeline_name="fake",
        started_at=NOW,
        completed_at=NOW,
        status="completed",
        adapter_name="fake-adapter",
        adapter_version="0.0.1",
    )


def _install_module(name: str, attrs: dict[str, object]) -> None:
    """Install a synthetic module into `sys.modules` so importlib finds it."""
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


class TestResolveAdapter:
    def test_returns_load_run_function_from_imported_module(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def load_run(path: Path) -> PipelineRun:
            return _make_run()

        monkeypatch.setitem(sys.modules, "fake_adapter_happy", types.ModuleType("x"))
        _install_module("fake_adapter_happy", {"load_run": load_run})

        resolved = resolve_adapter("fake_adapter_happy")

        assert resolved is load_run
        result = resolved(Path("anything.json"))
        assert isinstance(result, PipelineRun)
        assert result.run_id == "run_1"

    def test_missing_module_raises_adapter_error(self) -> None:
        with pytest.raises(AdapterError, match="Could not import adapter"):
            resolve_adapter("definitely.not.a.real.module.zzz_pipewise_test")

    def test_module_without_load_run_raises_adapter_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_module("fake_adapter_no_load_run", {"some_other_function": lambda: None})
        monkeypatch.setitem(
            sys.modules, "fake_adapter_no_load_run", sys.modules["fake_adapter_no_load_run"]
        )

        with pytest.raises(AdapterError, match="does not expose a 'load_run' function"):
            resolve_adapter("fake_adapter_no_load_run")

    def test_module_with_non_callable_load_run_raises_adapter_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_module("fake_adapter_bad_type", {"load_run": "not a function"})
        monkeypatch.setitem(
            sys.modules, "fake_adapter_bad_type", sys.modules["fake_adapter_bad_type"]
        )

        with pytest.raises(AdapterError, match="not callable"):
            resolve_adapter("fake_adapter_bad_type")

    def test_error_message_for_missing_module_includes_install_hint(self) -> None:
        with pytest.raises(AdapterError, match=r"uv pip install"):
            resolve_adapter("zzz_unimported_pipewise_test_module")

    def test_resolved_callable_returns_pipelinerun(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def load_run(path: Path) -> PipelineRun:
            assert path == Path("/tmp/run_42.json")
            return _make_run()

        _install_module("fake_adapter_returns_run", {"load_run": load_run})
        monkeypatch.setitem(
            sys.modules, "fake_adapter_returns_run", sys.modules["fake_adapter_returns_run"]
        )

        resolved = resolve_adapter("fake_adapter_returns_run")
        run = resolved(Path("/tmp/run_42.json"))
        assert isinstance(run, PipelineRun)


class TestResolveDefaultScorers:
    def test_returns_none_when_adapter_has_no_default_scorers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_module("fake_adapter_no_defaults", {"load_run": lambda p: None})
        monkeypatch.setitem(
            sys.modules,
            "fake_adapter_no_defaults",
            sys.modules["fake_adapter_no_defaults"],
        )
        assert resolve_default_scorers("fake_adapter_no_defaults") is None

    def test_returns_tuple_when_adapter_provides_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pipewise.scorers.budget import CostBudgetScorer
        from pipewise.scorers.exact_match import ExactMatchScorer

        def default_scorers() -> tuple[list[object], list[object]]:
            return (
                [ExactMatchScorer(fields=["title"])],
                [CostBudgetScorer(budget_usd=1.0)],
            )

        _install_module(
            "fake_adapter_with_defaults",
            {"load_run": lambda p: None, "default_scorers": default_scorers},
        )
        monkeypatch.setitem(
            sys.modules,
            "fake_adapter_with_defaults",
            sys.modules["fake_adapter_with_defaults"],
        )

        result = resolve_default_scorers("fake_adapter_with_defaults")
        assert result is not None
        step_scorers, run_scorers = result
        assert len(step_scorers) == 1
        assert len(run_scorers) == 1

    def test_non_callable_default_scorers_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_module(
            "fake_adapter_bad_defaults",
            {"load_run": lambda p: None, "default_scorers": "not callable"},
        )
        monkeypatch.setitem(
            sys.modules,
            "fake_adapter_bad_defaults",
            sys.modules["fake_adapter_bad_defaults"],
        )
        with pytest.raises(AdapterError, match="not callable"):
            resolve_default_scorers("fake_adapter_bad_defaults")

    def test_default_scorers_returning_wrong_shape_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_module(
            "fake_adapter_wrong_shape",
            {"load_run": lambda p: None, "default_scorers": lambda: "not a tuple"},
        )
        monkeypatch.setitem(
            sys.modules,
            "fake_adapter_wrong_shape",
            sys.modules["fake_adapter_wrong_shape"],
        )
        with pytest.raises(AdapterError, match="must return"):
            resolve_default_scorers("fake_adapter_wrong_shape")

    def test_missing_module_raises(self) -> None:
        with pytest.raises(AdapterError, match="Could not import adapter"):
            resolve_default_scorers("zzz_unimported_module_for_default_scorers")
