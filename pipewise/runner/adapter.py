"""Adapter resolution by module path.

Phase 3 #21 — decision LOCKED 2026-04-27. Adapters live in their pipeline's
repo, not in pipewise. The runner loads them at eval time via
`importlib.import_module(<module-path>)` and looks for a known module-level
function: `load_run(path: Path) -> PipelineRun`.

Why module-path import (not entry points): lowest friction for adapter
authors, no `pyproject.toml` ceremony, ModuleNotFoundError is the most
recognized Python error for this failure mode. Entry-point discovery becomes
the right call once the ecosystem has 5+ third-party adapters; until then
this is the simplest thing that works.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

from pipewise.core.schema import PipelineRun

AdapterCallable: TypeAlias = Callable[[Path], PipelineRun]
"""The contract every adapter module must satisfy.

A module-level function `load_run(path: Path) -> PipelineRun`. Given a path
to one of that pipeline's run artifacts (raw log file, JSON dump, etc.),
return the corresponding `PipelineRun`. Adapters are free to fetch from
remote storage, decompress archives, or whatever their pipeline needs —
pipewise is agnostic to how the run got produced.
"""

_EXPECTED_FUNCTION_NAME = "load_run"


class AdapterError(ImportError):
    """Raised when an adapter module cannot be loaded or is malformed."""


def resolve_adapter(name: str) -> AdapterCallable:
    """Import the adapter module and return its `load_run` function.

    Args:
        name: A dotted Python module path, e.g.
            ``"factspark.integrations.pipewise.adapter"``. The module must
            be importable from the current Python environment (installed
            package, in `PYTHONPATH`, etc.).

    Returns:
        The module's `load_run(path: Path) -> PipelineRun` function.

    Raises:
        AdapterError: the module can't be imported, or the imported module
            doesn't expose a callable named ``load_run``.
    """
    try:
        module = importlib.import_module(name)
    except ImportError as exc:
        raise AdapterError(
            f"Could not import adapter '{name}': {exc}. "
            "Make sure the adapter package is installed in the current "
            "environment (e.g., `uv pip install -e <path-to-adapter-repo>`)."
        ) from exc

    fn = getattr(module, _EXPECTED_FUNCTION_NAME, None)
    if fn is None:
        raise AdapterError(
            f"Adapter '{name}' does not expose a '{_EXPECTED_FUNCTION_NAME}' "
            f"function. Adapters must define "
            f"`{_EXPECTED_FUNCTION_NAME}(path: Path) -> PipelineRun` at module level."
        )
    if not callable(fn):
        raise AdapterError(
            f"Adapter '{name}' has '{_EXPECTED_FUNCTION_NAME}' but it is not "
            f"callable (got {type(fn).__name__})."
        )

    return fn  # type: ignore[no-any-return]


__all__ = ["AdapterCallable", "AdapterError", "resolve_adapter"]
