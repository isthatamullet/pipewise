"""Tests for `LlmJudgeScorer`.

Most tests use a fake Anthropic client so they're hermetic and free.
One test (`test_real_anthropic_api`) is gated behind `ANTHROPIC_API_KEY`
and runs against the real Anthropic API — it exercises the integration
end-to-end and is the Phase 2 validation gate for this scorer.
"""

import os
import sys
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pipewise import StepExecution, StepScorer
from pipewise.scorers.llm_judge import (
    CostCeilingExceeded,
    LlmJudgeScorer,
    _JudgeVerdict,
)

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _step(
    outputs: dict[str, object],
    step_id: str = "s1",
    inputs: dict[str, object] | None = None,
) -> StepExecution:
    return StepExecution(
        step_id=step_id,
        step_name=step_id.upper(),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        status="completed",
        inputs=inputs or {},
        outputs=outputs,
    )


# ─── Fake SDK plumbing ──────────────────────────────────────────────────


class _FakeUsage:
    def __init__(
        self,
        *,
        input_tokens: int = 100,
        output_tokens: int = 100,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _FakeParseResponse:
    def __init__(self, parsed: _JudgeVerdict, usage: _FakeUsage) -> None:
        self.parsed_output = parsed
        self.usage = usage


class _FakeMessages:
    def __init__(self, verdicts: Iterable[_JudgeVerdict], usage: _FakeUsage) -> None:
        # `verdicts` is consumed across calls — supports consensus tests.
        self._verdicts = iter(verdicts)
        self._usage = usage
        self.parse_calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> _FakeParseResponse:
        self.parse_calls.append(kwargs)
        try:
            verdict = next(self._verdicts)
        except StopIteration as e:
            raise AssertionError("FakeMessages.parse called more times than expected") from e
        return _FakeParseResponse(verdict, self._usage)


class _FakeClient:
    def __init__(
        self,
        verdicts: Iterable[_JudgeVerdict],
        usage: _FakeUsage | None = None,
    ) -> None:
        self.messages = _FakeMessages(verdicts, usage or _FakeUsage())


def _scorer_with_fake(
    *,
    rubric: str = "Output must be coherent.",
    verdicts: Iterable[_JudgeVerdict],
    usage: _FakeUsage | None = None,
    **kwargs: Any,
) -> tuple[LlmJudgeScorer, _FakeClient]:
    scorer = LlmJudgeScorer(rubric=rubric, **kwargs)
    fake = _FakeClient(verdicts, usage)
    scorer._client = fake
    return scorer, fake


# ─── Construction validation ─────────────────────────────────────────────


class TestConstruction:
    def test_satisfies_step_scorer_protocol(self) -> None:
        scorer = LlmJudgeScorer(rubric="x")
        assert isinstance(scorer, StepScorer)

    def test_default_model_is_sonnet(self) -> None:
        scorer = LlmJudgeScorer(rubric="x")
        assert scorer.model == "claude-sonnet-4-6"

    def test_default_consensus_is_one(self) -> None:
        scorer = LlmJudgeScorer(rubric="x")
        assert scorer.consensus_n == 1

    def test_default_cost_ceiling_is_5usd(self) -> None:
        scorer = LlmJudgeScorer(rubric="x")
        assert scorer.cost_ceiling_usd == 5.0

    def test_empty_rubric_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            LlmJudgeScorer(rubric="")
        with pytest.raises(ValueError, match="non-empty"):
            LlmJudgeScorer(rubric="   ")

    def test_consensus_n_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="consensus_n"):
            LlmJudgeScorer(rubric="x", consensus_n=0)

    def test_negative_cost_ceiling_rejected(self) -> None:
        with pytest.raises(ValueError, match="cost_ceiling_usd"):
            LlmJudgeScorer(rubric="x", cost_ceiling_usd=-1)

    def test_cost_ceiling_none_disables_check(self) -> None:
        scorer = LlmJudgeScorer(rubric="x", cost_ceiling_usd=None)
        assert scorer.cost_ceiling_usd is None

    def test_negative_max_retries_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            LlmJudgeScorer(rubric="x", max_retries=-1)

    def test_zero_max_tokens_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_tokens"):
            LlmJudgeScorer(rubric="x", max_tokens=0)

    def test_default_name_includes_model(self) -> None:
        assert LlmJudgeScorer(rubric="x").name == "llm_judge[claude-sonnet-4-6]"

    def test_custom_name_used(self) -> None:
        scorer = LlmJudgeScorer(rubric="x", name="my_judge")
        assert scorer.name == "my_judge"


# ─── Single-judge scoring ────────────────────────────────────────────────


class TestSingleJudge:
    def test_pass_verdict(self) -> None:
        scorer, _ = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=0.9, passed=True, reasoning="Looks good.")]
        )
        result = scorer.score(_step({"text": "Hello"}))
        assert result.passed is True
        assert result.score == 0.9
        assert result.reasoning == "Looks good."
        assert result.metadata["consensus_n"] == 1
        assert result.metadata["passed_count"] == 1
        assert result.metadata["model"] == "claude-sonnet-4-6"

    def test_fail_verdict(self) -> None:
        scorer, _ = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=0.2, passed=False, reasoning="Output is wrong.")]
        )
        result = scorer.score(_step({"text": "..."}))
        assert result.passed is False
        assert result.score == 0.2
        assert result.metadata["passed_count"] == 0

    def test_user_message_includes_outputs(self) -> None:
        scorer, fake = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")]
        )
        scorer.score(_step({"key": "VALUE_TO_FIND"}))
        call_kwargs = fake.messages.parse_calls[0]
        user_content = call_kwargs["messages"][0]["content"]
        assert "VALUE_TO_FIND" in user_content
        assert "Outputs" in user_content

    def test_user_message_includes_expected_when_provided(self) -> None:
        scorer, fake = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")]
        )
        scorer.score(
            _step({"text": "actual"}),
            _step({"text": "EXPECTED_TEXT"}),
        )
        user_content = fake.messages.parse_calls[0]["messages"][0]["content"]
        assert "EXPECTED_TEXT" in user_content
        assert "Expected" in user_content

    def test_user_message_omits_expected_section_when_absent(self) -> None:
        scorer, fake = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")]
        )
        scorer.score(_step({"text": "actual"}))
        user_content = fake.messages.parse_calls[0]["messages"][0]["content"]
        assert "Expected outputs" not in user_content


# ─── System prompt + caching ─────────────────────────────────────────────


class TestSystemPrompt:
    def test_rubric_in_system_block(self) -> None:
        scorer, fake = _scorer_with_fake(
            rubric="UNIQUE_RUBRIC_TEXT_12345",
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")],
        )
        scorer.score(_step({"text": "x"}))
        system = fake.messages.parse_calls[0]["system"]
        assert isinstance(system, list)
        assert "UNIQUE_RUBRIC_TEXT_12345" in system[0]["text"]

    def test_cache_control_on_system_block(self) -> None:
        scorer, fake = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")]
        )
        scorer.score(_step({"text": "x"}))
        system = fake.messages.parse_calls[0]["system"]
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_examples_included_when_provided(self) -> None:
        scorer, fake = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")],
            examples=["FIRST_EXAMPLE_BLOCK", "SECOND_EXAMPLE_BLOCK"],
        )
        scorer.score(_step({"text": "x"}))
        system_text = fake.messages.parse_calls[0]["system"][0]["text"]
        assert "FIRST_EXAMPLE_BLOCK" in system_text
        assert "SECOND_EXAMPLE_BLOCK" in system_text
        assert "Example 1" in system_text
        assert "Example 2" in system_text

    def test_examples_section_omitted_when_none(self) -> None:
        scorer, fake = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")]
        )
        scorer.score(_step({"text": "x"}))
        system_text = fake.messages.parse_calls[0]["system"][0]["text"]
        assert "Examples" not in system_text

    def test_system_prompt_stable_across_calls(self) -> None:
        # Same scorer + same rubric → identical system bytes (so cache hits work).
        scorer, fake = _scorer_with_fake(
            verdicts=[
                _JudgeVerdict(score=1.0, passed=True, reasoning="ok"),
                _JudgeVerdict(score=1.0, passed=True, reasoning="ok"),
            ]
        )
        scorer.score(_step({"text": "first"}))
        scorer.score(_step({"text": "second"}))
        system_a = fake.messages.parse_calls[0]["system"]
        system_b = fake.messages.parse_calls[1]["system"]
        assert system_a == system_b


# ─── Consensus ───────────────────────────────────────────────────────────


class TestConsensus:
    def test_three_pass_passes(self) -> None:
        scorer, fake = _scorer_with_fake(
            consensus_n=3,
            verdicts=[
                _JudgeVerdict(score=0.9, passed=True, reasoning="r1"),
                _JudgeVerdict(score=0.8, passed=True, reasoning="r2"),
                _JudgeVerdict(score=1.0, passed=True, reasoning="r3"),
            ],
        )
        result = scorer.score(_step({"text": "x"}))
        assert result.passed is True
        assert result.metadata["passed_count"] == 3
        assert result.metadata["majority_threshold"] == 2
        assert len(fake.messages.parse_calls) == 3
        # Average score
        assert abs(result.score - (0.9 + 0.8 + 1.0) / 3) < 1e-9

    def test_two_of_three_passes(self) -> None:
        scorer, _ = _scorer_with_fake(
            consensus_n=3,
            verdicts=[
                _JudgeVerdict(score=0.9, passed=True, reasoning="r1"),
                _JudgeVerdict(score=0.2, passed=False, reasoning="r2"),
                _JudgeVerdict(score=0.8, passed=True, reasoning="r3"),
            ],
        )
        result = scorer.score(_step({"text": "x"}))
        assert result.passed is True
        assert result.metadata["passed_count"] == 2

    def test_one_of_three_fails(self) -> None:
        scorer, _ = _scorer_with_fake(
            consensus_n=3,
            verdicts=[
                _JudgeVerdict(score=0.1, passed=False, reasoning="r1"),
                _JudgeVerdict(score=0.2, passed=False, reasoning="r2"),
                _JudgeVerdict(score=0.9, passed=True, reasoning="r3"),
            ],
        )
        result = scorer.score(_step({"text": "x"}))
        assert result.passed is False
        assert result.metadata["passed_count"] == 1

    def test_reasoning_concatenates_all_judges(self) -> None:
        scorer, _ = _scorer_with_fake(
            consensus_n=3,
            verdicts=[
                _JudgeVerdict(score=1.0, passed=True, reasoning="JUDGE_ONE_TEXT"),
                _JudgeVerdict(score=0.0, passed=False, reasoning="JUDGE_TWO_TEXT"),
                _JudgeVerdict(score=1.0, passed=True, reasoning="JUDGE_THREE_TEXT"),
            ],
        )
        result = scorer.score(_step({"text": "x"}))
        assert "JUDGE_ONE_TEXT" in (result.reasoning or "")
        assert "JUDGE_TWO_TEXT" in (result.reasoning or "")
        assert "JUDGE_THREE_TEXT" in (result.reasoning or "")
        assert "2/3" in (result.reasoning or "")

    def test_majority_threshold_for_n_5(self) -> None:
        scorer, _ = _scorer_with_fake(
            consensus_n=5,
            verdicts=[
                _JudgeVerdict(score=1.0, passed=True, reasoning="r"),
                _JudgeVerdict(score=1.0, passed=True, reasoning="r"),
                _JudgeVerdict(score=1.0, passed=True, reasoning="r"),
                _JudgeVerdict(score=0.0, passed=False, reasoning="r"),
                _JudgeVerdict(score=0.0, passed=False, reasoning="r"),
            ],
        )
        result = scorer.score(_step({"text": "x"}))
        assert result.metadata["majority_threshold"] == 3
        assert result.metadata["passed_count"] == 3
        assert result.passed is True

    def test_individual_verdicts_in_metadata(self) -> None:
        scorer, _ = _scorer_with_fake(
            consensus_n=2,
            verdicts=[
                _JudgeVerdict(score=0.9, passed=True, reasoning="r1"),
                _JudgeVerdict(score=0.8, passed=True, reasoning="r2"),
            ],
        )
        result = scorer.score(_step({"text": "x"}))
        verdicts = result.metadata["individual_verdicts"]
        assert len(verdicts) == 2
        assert verdicts[0]["reasoning"] == "r1"
        assert verdicts[0]["passed"] is True
        assert verdicts[0]["cost_usd"] > 0


# ─── Cost tracking + ceiling ─────────────────────────────────────────────


class TestCostTracking:
    def test_cost_tracked_per_call(self) -> None:
        # 100 in + 100 out on sonnet-4-6: $3/M * 100 + $15/M * 100 = $0.0018
        scorer, _ = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")]
        )
        result = scorer.score(_step({"text": "x"}))
        expected_cost = (100 / 1_000_000) * 3.0 + (100 / 1_000_000) * 15.0
        assert abs(scorer.cumulative_cost_usd - expected_cost) < 1e-9
        assert abs(result.metadata["scorer_cost_usd"] - expected_cost) < 1e-9

    def test_cumulative_cost_accumulates_across_score_calls(self) -> None:
        scorer, _ = _scorer_with_fake(
            verdicts=[
                _JudgeVerdict(score=1.0, passed=True, reasoning="ok"),
                _JudgeVerdict(score=1.0, passed=True, reasoning="ok"),
            ]
        )
        scorer.score(_step({"text": "x"}))
        cost_after_one = scorer.cumulative_cost_usd
        scorer.score(_step({"text": "y"}))
        cost_after_two = scorer.cumulative_cost_usd
        assert abs(cost_after_two - 2 * cost_after_one) < 1e-9

    def test_reset_cost(self) -> None:
        scorer, _ = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")]
        )
        scorer.score(_step({"text": "x"}))
        assert scorer.cumulative_cost_usd > 0
        scorer.reset_cost()
        assert scorer.cumulative_cost_usd == 0.0

    def test_cache_read_tokens_billed_at_lower_rate(self) -> None:
        # 1000 cache_read + 100 in + 100 out: cache reads are $0.30/M (10x cheaper than fresh input)
        usage = _FakeUsage(
            input_tokens=100,
            output_tokens=100,
            cache_read_input_tokens=1000,
        )
        scorer, _ = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")],
            usage=usage,
        )
        scorer.score(_step({"text": "x"}))
        expected = (
            (100 / 1_000_000) * 3.0
            + (100 / 1_000_000) * 15.0
            + (1000 / 1_000_000) * 0.30
        )
        assert abs(scorer.cumulative_cost_usd - expected) < 1e-9

    def test_unknown_model_uses_default_pricing(self) -> None:
        scorer, _ = _scorer_with_fake(
            model="totally-fake-model",
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="ok")],
        )
        scorer.score(_step({"text": "x"}))
        # Default sonnet pricing applied — same as the base test.
        expected_cost = (100 / 1_000_000) * 3.0 + (100 / 1_000_000) * 15.0
        assert abs(scorer.cumulative_cost_usd - expected_cost) < 1e-9


class TestCostCeiling:
    def test_aborts_when_ceiling_reached(self) -> None:
        # 1M input tokens at $3 = $3, 1M output at $15 = $15 → $18 per call
        big = _FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        scorer, _ = _scorer_with_fake(
            verdicts=[
                _JudgeVerdict(score=1.0, passed=True, reasoning="r"),
                _JudgeVerdict(score=1.0, passed=True, reasoning="r"),
            ],
            usage=big,
            cost_ceiling_usd=5.0,
        )
        # First call succeeds (pre-call check sees $0 cumulative).
        scorer.score(_step({"text": "first"}))
        assert scorer.cumulative_cost_usd >= 5.0
        # Second call's pre-check raises.
        with pytest.raises(CostCeilingExceeded, match="ceiling"):
            scorer.score(_step({"text": "second"}))

    def test_aborts_mid_consensus(self) -> None:
        # Each call costs $18; ceiling $5 → first call goes through, second is blocked.
        big = _FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        scorer, fake = _scorer_with_fake(
            consensus_n=3,
            verdicts=[
                _JudgeVerdict(score=1.0, passed=True, reasoning="r"),
                _JudgeVerdict(score=1.0, passed=True, reasoning="r"),
                _JudgeVerdict(score=1.0, passed=True, reasoning="r"),
            ],
            usage=big,
            cost_ceiling_usd=5.0,
        )
        with pytest.raises(CostCeilingExceeded):
            scorer.score(_step({"text": "x"}))
        # Only the first consensus call was made before the ceiling tripped.
        assert len(fake.messages.parse_calls) == 1

    def test_ceiling_disabled_with_none(self) -> None:
        big = _FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        scorer, _ = _scorer_with_fake(
            verdicts=[_JudgeVerdict(score=1.0, passed=True, reasoning="r")] * 3,
            usage=big,
            cost_ceiling_usd=None,
        )
        # Many costly calls, no exception.
        for _ in range(3):
            scorer.score(_step({"text": "x"}))
        assert scorer.cumulative_cost_usd > 5.0


# ─── Lazy import + SDK plumbing ──────────────────────────────────────────


class TestLazyImport:
    def test_anthropic_not_imported_until_score_call(self) -> None:
        # The Anthropic SDK is gated behind the [llm-judge] extra. Constructing
        # the scorer should not require it.
        # (We can construct a scorer; the import happens inside _get_client().)
        scorer = LlmJudgeScorer(rubric="x")
        assert scorer._client is None

    def test_clear_error_when_anthropic_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Block the import and confirm the error message points at the install.
        monkeypatch.setitem(sys.modules, "anthropic", None)
        scorer = LlmJudgeScorer(rubric="x")
        with pytest.raises(ImportError, match="llm-judge"):
            scorer._get_client()


# ─── Real-API integration test (gated) ───────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; skipping real-API integration test",
)
def test_real_anthropic_api() -> None:
    """End-to-end test against the real Anthropic API.

    This is the Phase 2 validation gate for LlmJudgeScorer. It exercises:
    - Real SDK initialization
    - Real prompt rendering (cached system + per-call user message)
    - Real `messages.parse()` with structured output validation
    - Real cost calculation against returned usage

    Skips on CI (no API key) but runs locally when the dev env has one.
    """
    rubric = (
        "The output must include a 'title' field that is a non-empty string. "
        "The 'title' should accurately reflect the content described in the "
        "step's 'inputs.url'. Score 1.0 for accurate, 0.5 for partial, 0.0 for missing."
    )
    scorer = LlmJudgeScorer(
        rubric=rubric,
        cost_ceiling_usd=1.0,  # tight ceiling for the test
    )

    # A clearly-passing case: the title matches the URL.
    good_step = _step(
        outputs={"title": "Example Domain"},
        inputs={"url": "https://example.com"},
    )
    result_good = scorer.score(good_step)
    assert result_good.passed is True
    assert result_good.score >= 0.5
    assert result_good.reasoning is not None and len(result_good.reasoning) > 0
    assert scorer.cumulative_cost_usd > 0

    # A clearly-failing case: title is missing entirely.
    bad_step = _step(
        outputs={},
        inputs={"url": "https://example.com"},
    )
    result_bad = scorer.score(bad_step)
    assert result_bad.passed is False
    assert result_bad.score < 0.5
