"""Run-time capture primitive: invoke a ``MinimalAgent`` and emit a ``PipelineRun``.

Wraps ``MinimalAgent.run(...)`` with an event sink that records each LLM
call as an ``agent__N`` ``StepExecution`` and each tool invocation as a
``<tool_name>__N`` step. Iteration suffixes follow the same always-suffixed
convention as the LangGraph adapter (see #78): single-fire steps get
``__1``; the suffix increments per repeat.

Per pipewise's determinism rule, this module performs the LLM calls and
writes the resulting ``PipelineRun`` JSON to disk. From that point on,
``adapter.py``'s eval-time reads are deterministic.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pipewise.core.schema import PipelineRun, StepExecution

from .agent import MinimalAgent
from .pricing import estimate_cost_usd

if TYPE_CHECKING:
    from anthropic import Anthropic

PROVIDER = "anthropic"


def _serialize_response(response: Any) -> dict[str, Any]:
    """Coerce an Anthropic ``Message`` into a JSON-round-trip-safe dict."""
    blocks: list[dict[str, Any]] = []
    for block in response.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            blocks.append({"type": "text", "text": getattr(block, "text", "")})
        elif block_type == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
        else:
            blocks.append({"type": block_type or "unknown"})
    return {
        "id": getattr(response, "id", None),
        "model": getattr(response, "model", None),
        "stop_reason": getattr(response, "stop_reason", None),
        "content": blocks,
    }


def capture_run(
    client: Anthropic,
    user_input: str,
    *,
    run_id: str,
    pipeline_name: str,
    system: str,
    tool_schemas: list[dict[str, Any]],
    tool_executors: dict[str, Any],
    pipeline_version: str = "0.1.0",
    adapter_version: str = "0.1.0",
    model: str | None = None,
) -> PipelineRun:
    """Invoke the agent on ``user_input`` and emit a ``PipelineRun``."""
    agent_kwargs: dict[str, Any] = {
        "client": client,
        "system": system,
        "tool_schemas": tool_schemas,
        "tool_executors": tool_executors,
    }
    if model is not None:
        agent_kwargs["model"] = model
    agent = MinimalAgent(**agent_kwargs)

    started_at = datetime.now(UTC)
    t_run_start = time.perf_counter()

    iteration_counter: dict[str, int] = defaultdict(int)
    steps: list[StepExecution] = []

    def sink(event_kind: str, event_data: dict[str, Any]) -> None:
        # Each chunk is recorded *after* the corresponding LLM/tool call has
        # finished, so per-step latency is not measurable inside this sink.
        # Run-level latency is the honest signal; step-level latency stays None.
        captured_at = datetime.now(UTC)
        if event_kind == "llm_call":
            response = event_data["response"]
            iteration_counter["agent"] += 1
            n = iteration_counter["agent"]
            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
            steps.append(
                StepExecution(
                    step_id=f"agent__{n}",
                    step_name=f"Agent (iteration {n})",
                    executor="agent",
                    model=getattr(response, "model", None),
                    provider=PROVIDER,
                    inputs={"messages": event_data["messages_in"]},
                    outputs=_serialize_response(response),
                    started_at=captured_at,
                    completed_at=captured_at,
                    status="completed",
                    input_tokens=input_tokens or None,
                    output_tokens=output_tokens or None,
                    cost_usd=estimate_cost_usd(
                        getattr(response, "model", "") or "",
                        input_tokens,
                        output_tokens,
                    ),
                    latency_ms=None,
                )
            )
        elif event_kind == "tool_call":
            name = event_data["name"]
            iteration_counter[name] += 1
            n = iteration_counter[name]
            steps.append(
                StepExecution(
                    step_id=f"{name}__{n}",
                    step_name=f"{name.replace('_', ' ').title()} (iteration {n})",
                    executor=name,
                    model=None,
                    provider=PROVIDER,
                    inputs={"input": event_data.get("input"), "tool_use_id": event_data.get("id")},
                    outputs={"output": event_data.get("output")},
                    started_at=captured_at,
                    completed_at=captured_at,
                    status="completed",
                    latency_ms=None,
                )
            )

    final_text = agent.run(user_input, sink=sink)

    completed_at = datetime.now(UTC)
    total_latency_ms = int((time.perf_counter() - t_run_start) * 1000)

    total_input = sum(s.input_tokens or 0 for s in steps)
    total_output = sum(s.output_tokens or 0 for s in steps)
    total_cost = sum((s.cost_usd or 0.0) for s in steps)

    return PipelineRun(
        run_id=run_id,
        pipeline_name=pipeline_name,
        pipeline_version=pipeline_version,
        adapter_name="pipewise-anthropic-quickstarts",
        adapter_version=adapter_version,
        started_at=started_at,
        completed_at=completed_at,
        status="completed",
        initial_input={"user_input": user_input},
        steps=steps,
        total_input_tokens=total_input or None,
        total_output_tokens=total_output or None,
        total_cost_usd=total_cost or None,
        total_latency_ms=total_latency_ms,
        final_output={"text": final_text},
    )


def write_run(run: PipelineRun, output_dir: Path) -> Path:
    """Write ``run`` to ``output_dir / <run_id>.json``. Returns the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{run.run_id}.json"
    out_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return out_path
