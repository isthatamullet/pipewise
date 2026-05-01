"""Tests for the capture primitive against mock LangGraph streams.

These tests do NOT make LLM calls — they construct deterministic mock graphs
that emit pre-built stream chunks. CI runs these on every PR.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, ToolMessage
from pipewise.core.schema import PipelineRun

from pipewise_langgraph.capture import _serialize, capture_run, write_run


class _MockGraph:
    """Stand-in for a LangGraph CompiledStateGraph. Yields a fixed chunk sequence."""

    def __init__(self, chunks: list[dict[str, Any]], topology: list[str]):
        self._chunks = chunks
        self._topology = topology

    def stream(self, _input: Any, *, stream_mode: str) -> Iterator[dict[str, Any]]:
        assert stream_mode == "updates"
        yield from self._chunks

    def get_graph(self) -> Any:
        nodes = MagicMock()
        nodes.keys = MagicMock(return_value=self._topology)
        result = MagicMock()
        result.nodes = nodes
        return result


def _ai(content: str, **kwargs: Any) -> AIMessage:
    return AIMessage(content=content, **kwargs)


def _tool(content: str, tool_call_id: str = "tc") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id, name="calc")


class TestCaptureRun:
    def test_iteration_naming_with_multiple_invocations(self):
        graph = _MockGraph(
            chunks=[
                {
                    "agent": {
                        "messages": [
                            _ai(
                                "calling tool",
                                usage_metadata={
                                    "input_tokens": 10,
                                    "output_tokens": 5,
                                    "total_tokens": 15,
                                },
                            )
                        ]
                    }
                },
                {"tools": {"messages": [_tool("42")]}},
                {
                    "agent": {
                        "messages": [
                            _ai(
                                "the answer is 42",
                                usage_metadata={
                                    "input_tokens": 20,
                                    "output_tokens": 8,
                                    "total_tokens": 28,
                                },
                            )
                        ]
                    }
                },
            ],
            topology=["__start__", "agent", "tools", "__end__"],
        )
        run = capture_run(
            graph,
            {"messages": []},
            run_id="t1",
            pipeline_name="test",
            model="m",
            provider="p",
        )
        step_ids = [s.step_id for s in run.steps]
        assert step_ids == ["agent__1", "tools__1", "agent__2"]
        assert all(s.status == "completed" for s in run.steps)

    def test_skipped_step_synthesized_when_node_never_fires(self):
        graph = _MockGraph(
            chunks=[
                {
                    "agent": {
                        "messages": [
                            _ai(
                                "hello, no tools needed",
                                usage_metadata={
                                    "input_tokens": 5,
                                    "output_tokens": 3,
                                    "total_tokens": 8,
                                },
                            )
                        ]
                    }
                },
            ],
            topology=["__start__", "agent", "tools", "__end__"],
        )
        run = capture_run(
            graph,
            {"messages": []},
            run_id="t2",
            pipeline_name="test",
            model="m",
            provider="p",
        )
        statuses = {s.step_id: s.status for s in run.steps}
        assert statuses == {"agent__1": "completed", "tools__1": "skipped"}

    def test_token_totals_sum_across_steps(self):
        graph = _MockGraph(
            chunks=[
                {
                    "agent": {
                        "messages": [
                            _ai(
                                "a",
                                usage_metadata={
                                    "input_tokens": 10,
                                    "output_tokens": 5,
                                    "total_tokens": 15,
                                },
                            )
                        ]
                    }
                },
                {
                    "agent": {
                        "messages": [
                            _ai(
                                "b",
                                usage_metadata={
                                    "input_tokens": 20,
                                    "output_tokens": 8,
                                    "total_tokens": 28,
                                },
                            )
                        ]
                    }
                },
            ],
            topology=["__start__", "agent", "__end__"],
        )
        run = capture_run(graph, {}, run_id="t3", pipeline_name="test")
        assert run.total_input_tokens == 30
        assert run.total_output_tokens == 13

    def test_run_status_completed_with_completed_at(self):
        graph = _MockGraph(
            chunks=[{"agent": {"messages": [_ai("done")]}}],
            topology=["agent"],
        )
        run = capture_run(graph, {}, run_id="t4", pipeline_name="test")
        assert run.status == "completed"
        assert run.completed_at is not None

    def test_total_latency_is_recorded(self):
        graph = _MockGraph(
            chunks=[{"agent": {"messages": [_ai("x")]}}],
            topology=["agent"],
        )
        run = capture_run(graph, {}, run_id="t5", pipeline_name="test")
        assert run.total_latency_ms is not None
        assert run.total_latency_ms >= 0


class TestSerialize:
    def test_serializes_ai_message(self):
        msg = AIMessage(
            content="hi",
            tool_calls=[{"name": "calc", "args": {"x": 1}, "id": "tc1"}],
        )
        result = _serialize(msg)
        assert result["type"] == "ai"
        assert result["content"] == "hi"
        assert result["tool_calls"][0]["name"] == "calc"

    def test_serializes_tool_message(self):
        msg = ToolMessage(content="42", tool_call_id="tc1", name="calc")
        result = _serialize(msg)
        assert result["type"] == "tool"
        assert result["tool_call_id"] == "tc1"
        assert result["name"] == "calc"

    def test_passthrough_for_primitives(self):
        assert _serialize("string") == "string"
        assert _serialize(42) == 42
        assert _serialize(None) is None

    def test_recurses_into_lists(self):
        result = _serialize([_ai("a"), _ai("b")])
        assert isinstance(result, list)
        assert all(item["type"] == "ai" for item in result)

    def test_recurses_into_dicts(self):
        result = _serialize({"messages": [_ai("a")], "other": 1})
        assert result["other"] == 1
        assert result["messages"][0]["type"] == "ai"


class TestWriteRun:
    def test_writes_json_to_disk(self, tmp_path):
        graph = _MockGraph(
            chunks=[{"agent": {"messages": [_ai("done")]}}],
            topology=["agent"],
        )
        run = capture_run(graph, {}, run_id="written", pipeline_name="test")
        out_path = write_run(run, tmp_path)
        assert out_path == tmp_path / "written.json"
        assert out_path.exists()

    def test_round_trip_json(self, tmp_path):
        graph = _MockGraph(
            chunks=[
                {
                    "agent": {
                        "messages": [
                            _ai(
                                "done",
                                usage_metadata={
                                    "input_tokens": 5,
                                    "output_tokens": 3,
                                    "total_tokens": 8,
                                },
                            )
                        ]
                    }
                }
            ],
            topology=["agent", "tools"],
        )
        run = capture_run(graph, {}, run_id="rt", pipeline_name="test")
        out_path = write_run(run, tmp_path)
        loaded = PipelineRun.model_validate_json(out_path.read_text(encoding="utf-8"))
        assert loaded.run_id == run.run_id
        assert len(loaded.steps) == len(run.steps)
        assert [s.step_id for s in loaded.steps] == [s.step_id for s in run.steps]
