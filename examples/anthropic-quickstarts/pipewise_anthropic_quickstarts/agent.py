"""Minimal Anthropic-SDK agent loop.

Mirrors the shape of upstream ``anthropics/anthropic-quickstarts/agents/agent.py``
without depending on the upstream code, which is intentionally not packaged
for install (per upstream's README, adopters translate the pattern into
their own code). The loop is deliberately small (<80 LOC) so adopters can
trace it end-to-end alongside their own pipewise adapter.

The loop emits "events" to a sink callable, which the capture primitive uses
to build ``StepExecution``s. Keeping side-effect emission separate from the
loop logic keeps the agent itself testable without any pipewise imports.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from anthropic.types import MessageParam, ToolParam, ToolUseBlock

if TYPE_CHECKING:
    from anthropic import Anthropic

EventSink = Callable[[str, dict[str, Any]], None]
"""Callback signature: ``sink(event_kind, event_data)``."""

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_MAX_ITERATIONS = 8


class MinimalAgent:
    """Claude-powered agent with tool use, modeled on the upstream Quickstart."""

    def __init__(
        self,
        client: Anthropic,
        system: str,
        tool_schemas: list[dict[str, Any]],
        tool_executors: dict[str, Callable[..., Any]],
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self.client = client
        self.system = system
        self.tool_schemas = tool_schemas
        self.tool_executors = tool_executors
        self.model = model
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations

    def run(self, user_input: str, *, sink: EventSink | None = None) -> str:
        """Run the agent loop until the model produces a final answer.

        Emits ``("llm_call", {...})`` and ``("tool_call", {...})`` events to
        the sink when present. Returns the final assistant text.
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_input}]

        for _ in range(self.max_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                tools=cast(list[ToolParam], self.tool_schemas),
                messages=cast(list[MessageParam], messages),
            )
            if sink is not None:
                sink("llm_call", {"response": response, "messages_in": list(messages)})

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                return _extract_final_text(response)

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if not isinstance(block, ToolUseBlock):
                    continue
                name = block.name
                tool_input = block.input
                executor = self.tool_executors.get(name)
                if executor is None:
                    output: Any = {"error": f"unknown tool {name!r}"}
                else:
                    try:
                        output = executor(**tool_input) if isinstance(tool_input, dict) else {}
                    except TypeError as exc:
                        output = {"error": f"invalid arguments for tool {name!r}: {exc}"}
                if sink is not None:
                    sink(
                        "tool_call",
                        {"name": name, "input": tool_input, "output": output, "id": block.id},
                    )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    }
                )

            if not tool_results:
                return _extract_final_text(response)
            messages.append({"role": "user", "content": tool_results})

        return _extract_final_text(response)


def _extract_final_text(response: Any) -> str:
    """Pull the assistant's text out of the final response, ignoring tool blocks."""
    parts = [getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text"]
    return "\n".join(p for p in parts if p)
