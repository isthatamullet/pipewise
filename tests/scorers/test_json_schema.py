"""Tests for `JsonSchemaScorer`."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pipewise import StepExecution, StepScorer
from pipewise.scorers.json_schema import JsonSchemaScorer

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _step(outputs: dict[str, Any], step_id: str = "s1") -> StepExecution:
    return StepExecution(
        step_id=step_id,
        step_name=step_id.upper(),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        status="completed",
        outputs=outputs,
    )


class TestJsonSchemaScorer:
    def test_satisfies_step_scorer_protocol(self) -> None:
        scorer = JsonSchemaScorer(schema={"type": "object"})
        assert isinstance(scorer, StepScorer)

    def test_valid_outputs_pass(self) -> None:
        schema = {
            "type": "object",
            "required": ["title", "rating"],
            "properties": {
                "title": {"type": "string"},
                "rating": {"type": "integer"},
            },
        }
        result = JsonSchemaScorer(schema=schema).score(_step({"title": "Hello", "rating": 80}))
        assert result.passed is True
        assert result.score == 1.0
        assert result.reasoning is None
        assert result.metadata["error_count"] == 0

    def test_missing_required_field_fails(self) -> None:
        schema = {
            "type": "object",
            "required": ["title", "rating"],
            "properties": {
                "title": {"type": "string"},
                "rating": {"type": "integer"},
            },
        }
        result = JsonSchemaScorer(schema=schema).score(_step({"title": "Hello"}))
        assert result.passed is False
        assert result.score == 0.0
        assert "rating" in (result.reasoning or "")
        assert result.metadata["error_count"] >= 1

    def test_wrong_type_fails(self) -> None:
        schema = {
            "type": "object",
            "properties": {"rating": {"type": "integer"}},
        }
        result = JsonSchemaScorer(schema=schema).score(_step({"rating": "high"}))
        assert result.passed is False
        assert "rating" in (result.reasoning or "")

    def test_nested_schema_valid(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "metadata": {
                    "type": "object",
                    "required": ["author"],
                    "properties": {
                        "author": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        }
        result = JsonSchemaScorer(schema=schema).score(
            _step({"metadata": {"author": "T", "tags": ["a", "b"]}})
        )
        assert result.passed is True

    def test_nested_schema_invalid_path_in_reasoning(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "metadata": {
                    "type": "object",
                    "required": ["author"],
                    "properties": {"author": {"type": "string"}},
                },
            },
        }
        result = JsonSchemaScorer(schema=schema).score(_step({"metadata": {}}))
        assert result.passed is False
        # Path should reference "metadata" so users see where it failed.
        assert "metadata" in (result.reasoning or "")

    def test_optional_field_not_required(self) -> None:
        schema = {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
            },
        }
        # Subtitle absent — optional, so this should pass.
        result = JsonSchemaScorer(schema=schema).score(_step({"title": "T"}))
        assert result.passed is True

    def test_multiple_errors_truncated_in_reasoning(self) -> None:
        # Schema that produces many errors.
        schema = {
            "type": "object",
            "required": ["a", "b", "c", "d", "e", "f", "g"],
        }
        result = JsonSchemaScorer(schema=schema).score(_step({}))
        assert result.passed is False
        assert result.metadata["error_count"] == 7
        # Reasoning truncates at 5 errors with a "... N more" suffix.
        assert "more" in (result.reasoning or "")

    def test_invalid_schema_raises_at_construction(self) -> None:
        # `type` should be a string or array, not an int.
        with pytest.raises(Exception):  # noqa: B017 — jsonschema.SchemaError details
            JsonSchemaScorer(schema={"type": 123})

    def test_default_name(self) -> None:
        assert JsonSchemaScorer(schema={"type": "object"}).name == "json_schema"

    def test_custom_name(self) -> None:
        scorer = JsonSchemaScorer(schema={"type": "object"}, name="my_schema")
        assert scorer.name == "my_schema"

    def test_expected_argument_ignored(self) -> None:
        # Self-contained — expected has no role here.
        actual = _step({"title": "Hello"})
        expected = _step({"title": "Different"})
        result = JsonSchemaScorer(schema={"type": "object"}).score(actual, expected)
        assert result.passed is True
