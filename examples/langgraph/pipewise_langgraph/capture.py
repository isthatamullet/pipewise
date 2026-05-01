"""Run-time capture primitive: invoke a LangGraph and emit a ``PipelineRun``.

The primitive walks ``graph.stream(input, stream_mode="updates")`` and emits one
``StepExecution`` per node invocation. Iterated nodes get suffixed step_ids
(``agent__1``, ``agent__2``); nodes present in graph topology that did not fire
during this run get a single ``status="skipped"`` step.

Per pipewise's determinism rule, this module performs the (non-deterministic)
LLM calls and writes the resulting ``PipelineRun`` JSON to disk. From that
point on, ``adapter.py``'s eval-time reads are deterministic.

## Iteration-naming convention

Always-suffixed: even single-fire nodes are recorded as ``<node>__1``. This
keeps step_ids mechanically uniform and lets adopters scan a captured run
without having to remember whether a given node "iterated."

This convention is reused by the Anthropic Quickstarts adapter (see Issue #79).
Refinements (e.g., nested-subgraph paths) should be added here first.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from pipewise.core.schema import PipelineRun, StepExecution
from pydantic import BaseModel


def _serialize(value: Any) -> Any:
    """Coerce LangChain types into JSON-round-trip-safe primitives.

    Handles ``BaseMessage``, ``Document``, Pydantic models, lists, and dicts.
    Other types pass through unchanged — Pydantic's JSON serializer will
    surface anything still non-serializable.
    """
    if isinstance(value, BaseMessage):
        result: dict[str, Any] = {"type": value.type, "content": value.content}
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            result["tool_calls"] = _serialize(tool_calls)
        tool_call_id = getattr(value, "tool_call_id", None)
        if tool_call_id:
            result["tool_call_id"] = tool_call_id
        msg_name = getattr(value, "name", None)
        if msg_name:
            result["name"] = msg_name
        return result
    if isinstance(value, Document):
        return {"page_content": value.page_content, "metadata": value.metadata}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    return value


def _extract_usage(messages: list[Any]) -> tuple[int, int]:
    """Sum ``usage_metadata`` across a list of messages.

    LangChain ``AIMessage`` exposes ``usage_metadata = {input_tokens, output_tokens, ...}``.
    Other message types have no usage; they contribute zero.
    """
    input_tokens = 0
    output_tokens = 0
    for msg in messages:
        usage = getattr(msg, "usage_metadata", None)
        if usage:
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
    return input_tokens, output_tokens


def capture_run(
    graph: Any,
    initial_input: dict[str, Any],
    *,
    run_id: str,
    pipeline_name: str,
    pipeline_version: str = "0.1.0",
    adapter_version: str = "0.1.0",
    model: str | None = None,
    provider: str | None = None,
) -> PipelineRun:
    """Invoke ``graph`` with ``initial_input`` and emit a ``PipelineRun``.

    Each chunk emitted by ``graph.stream(stream_mode="updates")`` becomes one
    ``StepExecution``. Nodes present in graph topology that never appear in
    the stream get one synthesized ``status="skipped"`` step with suffix ``__1``.
    """
    started_at = datetime.now(UTC)
    t_run_start = time.perf_counter()

    iteration_counter: dict[str, int] = defaultdict(int)
    seen_nodes: set[str] = set()
    steps: list[StepExecution] = []

    # `stream_mode="updates"` yields each chunk *after* the corresponding node
    # has finished, so per-step latency is not measurable from outside the
    # graph. We record run-level latency only; step-level latency stays None.
    for chunk in graph.stream(initial_input, stream_mode="updates"):
        for node_name, state_update in chunk.items():
            iteration_counter[node_name] += 1
            n = iteration_counter[node_name]
            seen_nodes.add(node_name)

            chunk_received_at = datetime.now(UTC)
            update = state_update or {}

            new_messages = update.get("messages", []) if isinstance(update, dict) else []
            input_tokens, output_tokens = _extract_usage(new_messages)

            steps.append(
                StepExecution(
                    step_id=f"{node_name}__{n}",
                    step_name=f"{node_name.replace('_', ' ').title()} (iteration {n})",
                    executor=node_name,
                    model=model,
                    provider=provider,
                    inputs={},
                    outputs=_serialize(update),
                    started_at=chunk_received_at,
                    completed_at=chunk_received_at,
                    status="completed",
                    input_tokens=input_tokens or None,
                    output_tokens=output_tokens or None,
                    latency_ms=None,
                )
            )

    topology_nodes = _topology_nodes(graph)
    for node_name in topology_nodes:
        if node_name not in seen_nodes:
            steps.append(
                StepExecution(
                    step_id=f"{node_name}__1",
                    step_name=f"{node_name.replace('_', ' ').title()} (iteration 1)",
                    executor=node_name,
                    model=model,
                    provider=provider,
                    inputs={},
                    outputs={},
                    started_at=datetime.now(UTC),
                    completed_at=None,
                    status="skipped",
                )
            )

    completed_at = datetime.now(UTC)
    total_latency_ms = int((time.perf_counter() - t_run_start) * 1000)

    total_input = sum(s.input_tokens or 0 for s in steps)
    total_output = sum(s.output_tokens or 0 for s in steps)

    return PipelineRun(
        run_id=run_id,
        pipeline_name=pipeline_name,
        pipeline_version=pipeline_version,
        adapter_name="pipewise-langgraph",
        adapter_version=adapter_version,
        started_at=started_at,
        completed_at=completed_at,
        status="completed",
        initial_input=_serialize(initial_input),
        steps=steps,
        total_input_tokens=total_input or None,
        total_output_tokens=total_output or None,
        total_latency_ms=total_latency_ms,
    )


def _topology_nodes(graph: Any) -> list[str]:
    """Return user-defined node names from the compiled graph topology.

    LangGraph injects ``__start__`` and ``__end__`` sentinel nodes; we exclude
    those because pipewise's schema is concerned with executor steps only.
    """
    nodes: list[str] = list(graph.get_graph().nodes.keys())
    return [n for n in nodes if not n.startswith("__")]


def write_run(run: PipelineRun, output_dir: Path) -> Path:
    """Write ``run`` to ``output_dir / <run_id>.json``. Returns the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{run.run_id}.json"
    out_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return out_path
