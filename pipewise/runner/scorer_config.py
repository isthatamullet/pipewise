"""TOML-based scorer configuration.

Phase 3 #25. The `--scorers <file>` flag on `pipewise eval` overrides the
adapter's default scorer set. The file is TOML with one section per scorer:

    [scorers.title-exact]
    class = "pipewise.scorers.exact_match.ExactMatchScorer"
    fields = ["title"]

    [scorers.cost-cap]
    class = "pipewise.scorers.budget.CostBudgetScorer"
    budget_usd = 0.50

The section key becomes the scorer's `name`. The `class` value is a dotted
import path to the scorer class. All other keys are forwarded as constructor
kwargs.
"""

from __future__ import annotations

import importlib
import tomllib
import typing
from pathlib import Path
from typing import Any

from pipewise.core.schema import PipelineRun, StepExecution
from pipewise.core.scorer import RunScorer, StepScorer


class ScorerConfigError(ValueError):
    """Raised when a scorer config file is malformed or refers to a missing class."""


def _import_scorer_class(class_path: str) -> type[Any]:
    if "." not in class_path:
        raise ScorerConfigError(
            f"Invalid scorer class path: '{class_path}'. "
            "Expected a dotted import path like "
            "'pipewise.scorers.exact_match.ExactMatchScorer'."
        )
    module_path, _, class_name = class_path.rpartition(".")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ScorerConfigError(
            f"Could not import module '{module_path}' for scorer class '{class_path}': {exc}"
        ) from exc
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ScorerConfigError(
            f"Module '{module_path}' has no attribute '{class_name}' (referenced by scorer config)."
        )
    if not isinstance(cls, type):
        raise ScorerConfigError(f"'{class_path}' is not a class (got {type(cls).__name__}).")
    return cls


def _instantiate_scorer(name: str, section: dict[str, Any]) -> object:
    if "class" not in section:
        raise ScorerConfigError(
            f"Scorer '{name}' is missing required 'class' key. "
            "Expected: class = '<dotted.import.path>'."
        )
    class_path = section["class"]
    if not isinstance(class_path, str):
        raise ScorerConfigError(f"Scorer '{name}' has non-string 'class' value: {class_path!r}.")
    cls = _import_scorer_class(class_path)
    kwargs = {k: v for k, v in section.items() if k != "class"}
    kwargs.setdefault("name", name)
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as exc:
        raise ScorerConfigError(
            f"Could not instantiate scorer '{name}' ({class_path}): {exc}"
        ) from exc


def load_scorer_config(path: Path) -> tuple[list[StepScorer], list[RunScorer]]:
    """Parse a TOML scorer-config file and return (step_scorers, run_scorers).

    Each scorer is classified by which Protocol it satisfies. A class that
    happens to satisfy both is treated as a `StepScorer` (the more specific
    fit in current pipewise practice — RunScorers operate on whole runs and
    don't typically also accept a `StepExecution`).

    Raises:
        FileNotFoundError: the config file does not exist.
        ScorerConfigError: the file is malformed, references a missing
            class, or instantiation fails.
    """
    if not path.exists():
        raise FileNotFoundError(f"Scorer config not found: {path}")

    raw = path.read_bytes()
    try:
        parsed = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ScorerConfigError(f"{path}: invalid TOML ({exc})") from exc

    sections = parsed.get("scorers", {})
    if not isinstance(sections, dict):
        raise ScorerConfigError(
            f"{path}: top-level 'scorers' must be a table, got {type(sections).__name__}."
        )

    step_scorers: list[StepScorer] = []
    run_scorers: list[RunScorer] = []
    for name, section in sections.items():
        if not isinstance(section, dict):
            raise ScorerConfigError(
                f"{path}: 'scorers.{name}' must be a table, got {type(section).__name__}."
            )
        instance = _instantiate_scorer(name, section)
        scope = _classify_scope(instance)
        if scope == "step" and isinstance(instance, StepScorer):
            step_scorers.append(instance)
        elif scope == "run" and isinstance(instance, RunScorer):
            run_scorers.append(instance)
        else:
            raise ScorerConfigError(
                f"{path}: scorer '{name}' ({section.get('class')}) does not satisfy "
                f"StepScorer or RunScorer protocol."
            )

    return step_scorers, run_scorers


def _classify_scope(instance: object) -> str | None:
    """Return 'step', 'run', or None based on the scorer's `score(actual=...)` annotation.

    Both Protocols are runtime-checkable and have identical attribute shape
    (`name`, `score`), so plain `isinstance` matches both. The discriminator
    is the type of the `score` method's `actual` parameter: `StepExecution`
    for step scorers, `PipelineRun` for run scorers.
    """
    score_fn = getattr(instance, "score", None)
    if score_fn is None or not callable(score_fn):
        return None
    try:
        hints = typing.get_type_hints(score_fn)
    except Exception:
        hints = {}
    actual_type = hints.get("actual")
    if actual_type is StepExecution:
        return "step"
    if actual_type is PipelineRun:
        return "run"
    # Fallback: if exactly one Protocol matches, use it. (Both will usually
    # match given identical attribute shape, so this rarely disambiguates;
    # included as a safety net for scorers without resolvable type hints.)
    is_step = isinstance(instance, StepScorer)
    is_run = isinstance(instance, RunScorer)
    if is_step and not is_run:
        return "step"
    if is_run and not is_step:
        return "run"
    return None


__all__ = ["ScorerConfigError", "load_scorer_config"]
