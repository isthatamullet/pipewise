"""Pretty-printer for `PipelineRun` files.

Phase 3 #24. Plain-text formatter for the `pipewise inspect` command — keeps
the runtime dep set lean (no `rich`). Long string values in inputs/outputs
are truncated by default to keep the output scannable; `--full` skips
truncation; `--keys` shows top-level structure (key + type/size) instead
of values, which is the readable mode for real-pipeline data where steps
share a lot of common content (the leading bytes of value-truncated
previews end up identical).
"""

from __future__ import annotations

from typing import Any

from pipewise.core.schema import PipelineRun, StepExecution

_DEFAULT_TRUNCATE_AT = 80
_TRUNCATE_SUFFIX = "…"


def _truncate(value: Any, limit: int = _DEFAULT_TRUNCATE_AT) -> str:
    """Stringify a value and truncate to ``limit`` characters with an ellipsis."""
    rendered = repr(value)
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 1] + _TRUNCATE_SUFFIX


def _summarize_value(value: Any) -> str:
    """One-token type/size summary for keys-mode rendering.

    `dict[N]` / `list[N]` / `tuple[N]` / `set[N]` carry the container length;
    primitives render as their type name; `None` renders as `None`; anything
    unrecognized falls back to the class name.
    """
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, tuple):
        return f"tuple[{len(value)}]"
    if isinstance(value, set):
        return f"set[{len(value)}]"
    return type(value).__name__


def _render_kv_keys(d: dict[str, Any]) -> str:
    """Render an inputs/outputs dict as a top-level structural summary.

    Each top-level entry becomes `'key': <type-summary>` so adopters can see
    what a step actually produced without dumping content. Keys are repr'd
    (matches `_render_kv_dict`) so keys containing spaces, colons, or other
    special characters render unambiguously. One level only — nested
    dicts/lists are summarized as `dict[N]`/`list[N]` rather than expanded
    recursively.
    """
    if not d:
        return "{}"
    items = [f"{k!r}: {_summarize_value(v)}" for k, v in d.items()]
    return "{" + ", ".join(items) + "}"


def _render_kv_dict(d: dict[str, Any], full: bool) -> str:
    """Render an inputs/outputs dict for inline display."""
    if not d:
        return "{}"
    if full:
        return repr(d)
    items = [f"{k!r}: {_truncate(v)}" for k, v in d.items()]
    inner = ", ".join(items)
    if len(inner) > _DEFAULT_TRUNCATE_AT * 2:
        inner = inner[: _DEFAULT_TRUNCATE_AT * 2 - 1] + _TRUNCATE_SUFFIX
    return "{" + inner + "}"


def _format_duration(step: StepExecution) -> str:
    if step.completed_at is None:
        return "(no completed_at)"
    delta = step.completed_at - step.started_at
    return f"{delta.total_seconds():.2f}s"


def _format_step(idx: int, step: StepExecution, full: bool, keys: bool) -> list[str]:
    bits: list[str] = []
    header_parts = [f"{idx}. {step.step_id} [{step.status}]"]
    if step.executor:
        header_parts.append(step.executor)
    if step.model:
        header_parts.append(f"@ {step.model}")
    if step.cost_usd is not None:
        header_parts.append(f"cost=${step.cost_usd:.4f}")
    if step.latency_ms is not None:
        header_parts.append(f"latency={step.latency_ms}ms")
    bits.append("  " + " ".join(header_parts) + f"  ({_format_duration(step)})")
    if keys:
        bits.append(f"     inputs:  {_render_kv_keys(step.inputs)}")
        bits.append(f"     outputs: {_render_kv_keys(step.outputs)}")
    else:
        bits.append(f"     inputs:  {_render_kv_dict(step.inputs, full)}")
        bits.append(f"     outputs: {_render_kv_dict(step.outputs, full)}")
    if step.error:
        bits.append(f"     error:   {step.error if full else _truncate(step.error)}")
    return bits


def format_run(run: PipelineRun, full: bool = False, keys: bool = False) -> str:
    """Render a `PipelineRun` as a multi-line plain-text summary.

    Args:
        run: The run to format.
        full: When True, do not truncate long string values. Mutually
            exclusive with ``keys`` — caller is responsible for not
            passing both.
        keys: When True, render inputs/outputs as a top-level structural
            summary (`key: <type-summary>`) instead of value-truncated
            previews. Useful for real-pipeline runs where steps share a
            lot of common content.
    """
    if full and keys:
        raise ValueError("format_run: 'full' and 'keys' are mutually exclusive")
    lines: list[str] = []
    pipeline_id = run.pipeline_name + (f"@{run.pipeline_version}" if run.pipeline_version else "")
    adapter_id = f"{run.adapter_name}@{run.adapter_version}"

    lines.append(f"Run:      {run.run_id}")
    lines.append(f"Pipeline: {pipeline_id}")
    lines.append(f"Adapter:  {adapter_id}")

    duration = "(running)"
    if run.completed_at is not None:
        duration = f"{(run.completed_at - run.started_at).total_seconds():.2f}s"
    lines.append(
        f"Status:   {run.status}  Started: {run.started_at.isoformat()}  Duration: {duration}"
    )

    lines.append("")
    lines.append(f"Steps ({len(run.steps)}):")
    if not run.steps:
        lines.append("  (none)")
    for idx, step in enumerate(run.steps, start=1):
        lines.extend(_format_step(idx, step, full, keys))

    totals: list[str] = []
    if run.total_cost_usd is not None:
        totals.append(f"cost=${run.total_cost_usd:.4f}")
    if run.total_latency_ms is not None:
        totals.append(f"latency={run.total_latency_ms}ms")
    if run.total_input_tokens is not None:
        totals.append(f"input_tokens={run.total_input_tokens}")
    if run.total_output_tokens is not None:
        totals.append(f"output_tokens={run.total_output_tokens}")
    if totals:
        lines.append("")
        lines.append("Totals: " + " ".join(totals))

    return "\n".join(lines)


__all__ = ["format_run"]
