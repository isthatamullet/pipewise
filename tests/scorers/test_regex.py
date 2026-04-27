"""Tests for `RegexScorer`."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from pipewise import StepExecution, StepScorer
from pipewise.scorers.regex import RegexScorer

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


class TestRegexScorer:
    def test_satisfies_step_scorer_protocol(self) -> None:
        scorer = RegexScorer(field="x", pattern=".*")
        assert isinstance(scorer, StepScorer)

    def test_search_match_passes(self) -> None:
        result = RegexScorer(field="text", pattern=r"\d+").score(
            _step({"text": "Order 12345 received"})
        )
        assert result.passed is True
        assert result.score == 1.0
        assert result.reasoning is None

    def test_search_no_match_fails(self) -> None:
        result = RegexScorer(field="text", pattern=r"\d+").score(
            _step({"text": "no digits here"})
        )
        assert result.passed is False
        assert result.score == 0.0
        assert "did not search" in (result.reasoning or "")

    def test_fullmatch_mode_strict(self) -> None:
        scorer = RegexScorer(field="id", pattern=r"[A-Z]{3}\d{3}", match_mode="fullmatch")
        assert scorer.score(_step({"id": "ABC123"})).passed is True
        # Has prefix junk → fullmatch fails, but search would pass.
        assert scorer.score(_step({"id": "junk-ABC123"})).passed is False

    def test_match_mode_anchors_at_start(self) -> None:
        scorer = RegexScorer(field="text", pattern=r"hello", match_mode="match")
        assert scorer.score(_step({"text": "hello world"})).passed is True
        assert scorer.score(_step({"text": "world hello"})).passed is False

    def test_missing_field_handled(self) -> None:
        result = RegexScorer(field="absent", pattern=r".*").score(_step({"present": "x"}))
        assert result.passed is False
        assert result.score == 0.0
        assert "missing from outputs" in (result.reasoning or "")

    def test_non_string_field_handled(self) -> None:
        result = RegexScorer(field="count", pattern=r"\d+").score(_step({"count": 42}))
        assert result.passed is False
        assert result.score == 0.0
        assert "not str" in (result.reasoning or "")

    def test_accepts_compiled_pattern(self) -> None:
        compiled = re.compile(r"^\d{4}$")
        result = RegexScorer(field="year", pattern=compiled).score(_step({"year": "2026"}))
        assert result.passed is True

    def test_empty_string_field_with_match_anything_passes(self) -> None:
        # Regex semantics: re.search("", "") matches at position 0.
        result = RegexScorer(field="x", pattern=r"").score(_step({"x": ""}))
        assert result.passed is True

    def test_empty_field_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty field name"):
            RegexScorer(field="", pattern=r".*")

    def test_default_name(self) -> None:
        assert RegexScorer(field="title", pattern=r".*").name == "regex[title]"

    def test_custom_name(self) -> None:
        assert (
            RegexScorer(field="title", pattern=r".*", name="my_regex").name == "my_regex"
        )

    def test_metadata_includes_pattern_and_mode(self) -> None:
        result = RegexScorer(field="x", pattern=r"foo", match_mode="search").score(
            _step({"x": "foobar"})
        )
        assert result.metadata == {"pattern": "foo", "mode": "search"}

    def test_expected_argument_ignored(self) -> None:
        # RegexScorer should not require expected; passing one is benign.
        actual = _step({"x": "value"})
        expected = _step({"x": "different"})
        result = RegexScorer(field="x", pattern=r"value").score(actual, expected)
        assert result.passed is True
