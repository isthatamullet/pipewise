"""Tests for `ExactMatchScorer`."""

from datetime import UTC, datetime, timedelta

import pytest

from pipewise import StepExecution, StepScorer
from pipewise.scorers.exact_match import ExactMatchScorer

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _step(outputs: dict[str, object], step_id: str = "s1") -> StepExecution:
    return StepExecution(
        step_id=step_id,
        step_name=step_id.upper(),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        status="completed",
        outputs=outputs,
    )


class TestExactMatchScorer:
    def test_satisfies_step_scorer_protocol(self) -> None:
        scorer = ExactMatchScorer(fields=["title"])
        assert isinstance(scorer, StepScorer)

    def test_full_match_on_single_field_passes(self) -> None:
        actual = _step({"title": "Hello"})
        expected = _step({"title": "Hello"})
        result = ExactMatchScorer(fields=["title"]).score(actual, expected)
        assert result.passed is True
        assert result.score == 1.0
        assert result.reasoning is None
        assert result.metadata["matched_fields"] == ["title"]
        assert result.metadata["mismatched_fields"] == []
        assert result.metadata["missing_fields"] == []

    def test_full_match_multi_field_passes(self) -> None:
        actual = _step({"title": "Hello", "summary": "World"})
        expected = _step({"title": "Hello", "summary": "World"})
        result = ExactMatchScorer(fields=["title", "summary"]).score(actual, expected)
        assert result.passed is True
        assert result.score == 1.0

    def test_partial_match_fails_with_fractional_score(self) -> None:
        actual = _step({"title": "Hello", "summary": "Drift"})
        expected = _step({"title": "Hello", "summary": "World"})
        result = ExactMatchScorer(fields=["title", "summary"]).score(actual, expected)
        assert result.passed is False
        assert result.score == 0.5
        assert "mismatch" in (result.reasoning or "")
        assert result.metadata["matched_fields"] == ["title"]
        assert len(result.metadata["mismatched_fields"]) == 1
        bad = result.metadata["mismatched_fields"][0]
        assert bad["field"] == "summary"
        assert bad["actual"] == "Drift"
        assert bad["expected"] == "World"

    def test_total_mismatch_zero_score(self) -> None:
        actual = _step({"a": 1, "b": 2})
        expected = _step({"a": 99, "b": 99})
        result = ExactMatchScorer(fields=["a", "b"]).score(actual, expected)
        assert result.passed is False
        assert result.score == 0.0

    def test_missing_field_in_actual_counts_as_missing(self) -> None:
        actual = _step({"title": "Hello"})
        expected = _step({"title": "Hello", "summary": "World"})
        result = ExactMatchScorer(fields=["title", "summary"]).score(actual, expected)
        assert result.passed is False
        assert result.score == 0.5
        assert result.metadata["missing_fields"] == ["summary"]

    def test_missing_field_in_expected_counts_as_missing(self) -> None:
        actual = _step({"title": "Hello", "summary": "World"})
        expected = _step({"title": "Hello"})
        result = ExactMatchScorer(fields=["title", "summary"]).score(actual, expected)
        assert result.passed is False
        assert result.metadata["missing_fields"] == ["summary"]

    def test_deep_equality_on_nested_dicts_passes(self) -> None:
        nested = {"data": {"nested": {"deep": [1, 2, {"k": "v"}]}}}
        actual = _step(nested)
        expected = _step({"data": {"nested": {"deep": [1, 2, {"k": "v"}]}}})
        result = ExactMatchScorer(fields=["data"]).score(actual, expected)
        assert result.passed is True
        assert result.score == 1.0

    def test_deep_inequality_on_nested_dicts_fails(self) -> None:
        actual = _step({"data": {"nested": [1, 2, 3]}})
        expected = _step({"data": {"nested": [1, 2, 4]}})
        result = ExactMatchScorer(fields=["data"]).score(actual, expected)
        assert result.passed is False
        assert result.score == 0.0

    def test_expected_required(self) -> None:
        actual = _step({"title": "Hello"})
        with pytest.raises(ValueError, match="requires an `expected` step"):
            ExactMatchScorer(fields=["title"]).score(actual)

    def test_empty_fields_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires at least one field"):
            ExactMatchScorer(fields=[])

    def test_default_name_includes_fields(self) -> None:
        assert ExactMatchScorer(fields=["title"]).name == "exact_match[title]"
        assert ExactMatchScorer(fields=["title", "summary"]).name == "exact_match[title,summary]"

    def test_custom_name_used(self) -> None:
        scorer = ExactMatchScorer(fields=["title"], name="my_scorer")
        assert scorer.name == "my_scorer"
