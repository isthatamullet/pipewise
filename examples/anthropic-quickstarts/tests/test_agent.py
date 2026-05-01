"""Tests for the MinimalAgent loop using a mocked Anthropic client.

These do NOT call the real Anthropic API — they construct deterministic stub
responses to verify loop control flow, tool dispatch, and event emission.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pipewise_anthropic_quickstarts.agent import MinimalAgent
from pipewise_anthropic_quickstarts.tools import TOOL_EXECUTORS, TOOL_SCHEMAS


def _text_block(text: str) -> Any:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _tool_use_block(name: str, args: dict[str, Any], block_id: str = "tu_1") -> Any:
    """Build a stub that passes ``isinstance(block, ToolUseBlock)``."""
    from anthropic.types import ToolUseBlock

    return ToolUseBlock(
        id=block_id,
        name=name,
        input=args,
        type="tool_use",
    )


def _response(content: list[Any], stop_reason: str, model: str = "test-model") -> Any:
    response = MagicMock()
    response.content = content
    response.stop_reason = stop_reason
    response.model = model
    response.usage = MagicMock()
    response.usage.input_tokens = 10
    response.usage.output_tokens = 5
    return response


def _client_returning(*responses: Any) -> Any:
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = MagicMock(side_effect=list(responses))
    return client


class TestMinimalAgentLoop:
    def test_terminates_on_end_turn_without_tools(self):
        client = _client_returning(_response([_text_block("hello back")], "end_turn"))
        agent = MinimalAgent(
            client=client,
            system="sys",
            tool_schemas=TOOL_SCHEMAS,
            tool_executors=TOOL_EXECUTORS,
        )
        events: list[tuple[str, dict[str, Any]]] = []
        result = agent.run("hi", sink=lambda k, d: events.append((k, d)))
        assert result == "hello back"
        assert [k for k, _ in events] == ["llm_call"]
        assert client.messages.create.call_count == 1

    def test_iterates_through_tool_call_then_returns(self):
        client = _client_returning(
            _response(
                [_tool_use_block("calculator", {"expression": "1+1"}, "tu_a")],
                "tool_use",
            ),
            _response([_text_block("the answer is 2")], "end_turn"),
        )
        agent = MinimalAgent(
            client=client,
            system="sys",
            tool_schemas=TOOL_SCHEMAS,
            tool_executors=TOOL_EXECUTORS,
        )
        events: list[tuple[str, dict[str, Any]]] = []
        result = agent.run("compute 1+1", sink=lambda k, d: events.append((k, d)))
        assert result == "the answer is 2"
        kinds = [k for k, _ in events]
        assert kinds == ["llm_call", "tool_call", "llm_call"]
        tool_event = events[1][1]
        assert tool_event["name"] == "calculator"
        assert tool_event["output"] == "2"

    def test_unknown_tool_returns_error_payload(self):
        client = _client_returning(
            _response(
                [_tool_use_block("nonexistent_tool", {}, "tu_x")],
                "tool_use",
            ),
            _response([_text_block("ok")], "end_turn"),
        )
        agent = MinimalAgent(
            client=client,
            system="sys",
            tool_schemas=TOOL_SCHEMAS,
            tool_executors=TOOL_EXECUTORS,
        )
        events: list[tuple[str, dict[str, Any]]] = []
        agent.run("test", sink=lambda k, d: events.append((k, d)))
        tool_event = next(d for k, d in events if k == "tool_call")
        assert "error" in tool_event["output"]

    def test_max_iterations_caps_loop(self):
        # Always returns tool_use → would loop forever; max_iterations stops it.
        looping_response = _response(
            [_tool_use_block("calculator", {"expression": "1"}, "tu_loop")],
            "tool_use",
        )
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = MagicMock(return_value=looping_response)
        agent = MinimalAgent(
            client=client,
            system="sys",
            tool_schemas=TOOL_SCHEMAS,
            tool_executors=TOOL_EXECUTORS,
            max_iterations=3,
        )
        agent.run("loop")
        assert client.messages.create.call_count == 3

    def test_runs_without_sink(self):
        client = _client_returning(_response([_text_block("ok")], "end_turn"))
        agent = MinimalAgent(
            client=client,
            system="sys",
            tool_schemas=TOOL_SCHEMAS,
            tool_executors=TOOL_EXECUTORS,
        )
        # Smoke test: passing no sink is supported and shouldn't raise.
        result = agent.run("hi")
        assert result == "ok"


@pytest.mark.parametrize("user_input", ["", "x" * 5000])
def test_run_handles_extreme_inputs(user_input: str):
    client = _client_returning(_response([_text_block("ok")], "end_turn"))
    agent = MinimalAgent(
        client=client,
        system="sys",
        tool_schemas=TOOL_SCHEMAS,
        tool_executors=TOOL_EXECUTORS,
    )
    assert agent.run(user_input) == "ok"
