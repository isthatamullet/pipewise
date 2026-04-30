"""LlmJudgeScorer — use Claude as a judge to score a step's output against a rubric.

Anthropic-only in v1 (see BACKLOG for multi-provider plans). Uses the
Anthropic SDK's structured-output parsing (`messages.parse`) so the verdict
is validated against a Pydantic schema before reaching the scorer's logic —
no text-parsing, no JSON-fragment recovery.

## Caching

The rubric (and any examples) typically dominate the prompt and are stable
across runs. Both go in a `cache_control={"type": "ephemeral"}` system block
at the start of every call, so the first call writes the cache and every
subsequent call reads it at ~0.1x the input cost. The user message — step
inputs, outputs, optional expected — comes after the cache breakpoint and
varies per step.

## Consensus

`consensus_n` controls how many independent judge calls vote on each step.
The default is N=1 (single call, cheapest). Set N=3 for production CI to
mitigate single-judge non-determinism — the verdict passes when at least
`(N // 2) + 1` calls agree it passed (majority).

## Cost ceiling

Each scorer instance tracks cumulative API spend and aborts before any
new call when the running total has met or exceeded `cost_ceiling_usd`.
The check is pre-call, so a single call may slightly overshoot the ceiling
(by at most the cost of one call). Set `cost_ceiling_usd=None` to disable.

## Retries

Delegates to the Anthropic SDK's automatic retry logic (`max_retries`).
The SDK retries 5xx, 408, 409, 429 with exponential backoff; 4xx other
than 429 fails fast — exactly the policy v1 needs.
"""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from pipewise.core.schema import StepExecution
from pipewise.core.scorer import ScoreResult


class CostCeilingExceeded(RuntimeError):
    """Raised when LlmJudgeScorer would exceed its configured cost ceiling."""


class _JudgeVerdict(BaseModel):
    """Validated structured output from a single judge call."""

    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    reasoning: str


# Per-million-token pricing (USD) for models pipewise ships defaults for.
# Used to convert token counts in API responses to dollar amounts for the
# cost ceiling. Unknown models fall back to the default model's pricing
# with a warning in metadata.
_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write_5m": 3.75,
    },
    "claude-opus-4-7": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_write_5m": 6.25,
    },
    "claude-opus-4-6": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_write_5m": 6.25,
    },
    "claude-haiku-4-5": {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.10,
        "cache_write_5m": 1.25,
    },
}


class LlmJudgeScorer:
    """Score a step's output using a Claude judge model and a rubric."""

    DEFAULT_MODEL = "claude-sonnet-4-6"
    DEFAULT_COST_CEILING_USD = 5.0
    DEFAULT_MAX_TOKENS = 2000

    def __init__(
        self,
        rubric: str,
        *,
        model: str = DEFAULT_MODEL,
        examples: Sequence[str] | None = None,
        consensus_n: int = 1,
        cost_ceiling_usd: float | None = DEFAULT_COST_CEILING_USD,
        max_retries: int = 2,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
        name: str | None = None,
        applies_to_step_ids: Sequence[str] | None = None,
    ) -> None:
        if not rubric or not rubric.strip():
            raise ValueError("rubric must be a non-empty string")
        if consensus_n < 1:
            raise ValueError("consensus_n must be >= 1")
        if cost_ceiling_usd is not None and cost_ceiling_usd < 0:
            raise ValueError("cost_ceiling_usd must be non-negative or None")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")

        self.rubric = rubric
        self.model = model
        self.examples: list[str] = list(examples or [])
        self.consensus_n = consensus_n
        self.cost_ceiling_usd = cost_ceiling_usd
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self._api_key = api_key
        self.name = name or f"llm_judge[{model}]"
        self.applies_to_step_ids: Sequence[str] | None = (
            tuple(applies_to_step_ids) if applies_to_step_ids is not None else None
        )

        self._client: Any = None
        self._cumulative_cost_usd: float = 0.0

    # ─── Public state ────────────────────────────────────────────────────

    @property
    def cumulative_cost_usd(self) -> float:
        """Total USD spent on API calls by this scorer instance, so far."""
        return self._cumulative_cost_usd

    def reset_cost(self) -> None:
        """Reset the cumulative cost counter to zero (does not reset the ceiling)."""
        self._cumulative_cost_usd = 0.0

    # ─── Scoring ─────────────────────────────────────────────────────────

    def score(
        self,
        actual: StepExecution,
        expected: StepExecution | None = None,
    ) -> ScoreResult:
        system_blocks = self._build_system_prompt()
        user_message = self._build_user_message(actual, expected)

        verdicts: list[dict[str, Any]] = []
        for i in range(self.consensus_n):
            self._check_cost_ceiling(call_index=i)
            verdict, cost = self._call_judge(system_blocks, user_message)
            self._cumulative_cost_usd += cost
            verdict["cost_usd"] = cost
            verdicts.append(verdict)

        return self._aggregate(verdicts)

    # ─── Internal: prompt construction ───────────────────────────────────

    def _build_system_prompt(self) -> list[dict[str, Any]]:
        """Build the cacheable system prompt block(s).

        The full rubric and examples are concatenated into one text block
        with a single `cache_control` breakpoint. Pipewise's API surface
        treats the rubric as opaque text — we don't massage it.
        """
        parts: list[str] = [
            "You are an expert evaluator. Your job is to score the output "
            "of one step in a multi-step LLM pipeline against a rubric, "
            "and return a structured verdict.\n\n",
            "## Rubric\n\n",
            self.rubric.rstrip(),
            "\n",
        ]
        if self.examples:
            parts.append("\n## Examples\n\n")
            for i, ex in enumerate(self.examples, start=1):
                parts.append(f"### Example {i}\n\n{ex.rstrip()}\n\n")
        parts.append(
            "\n## Output format\n\n"
            "Return a structured verdict with three fields:\n"
            "- `score`: a float in [0.0, 1.0] (1.0 = perfect; 0.0 = total failure)\n"
            "- `passed`: a boolean — does this output meet the rubric?\n"
            "- `reasoning`: a brief free-text explanation of your verdict.\n"
        )
        text = "".join(parts)
        return [
            {
                "type": "text",
                "text": text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _build_user_message(
        self,
        actual: StepExecution,
        expected: StepExecution | None,
    ) -> str:
        import json

        parts: list[str] = [
            "Evaluate this step's output against the rubric.\n\n",
            f"Step ID: {actual.step_id}\n",
            f"Step name: {actual.step_name}\n",
        ]
        if actual.executor:
            parts.append(f"Executor: {actual.executor}\n")
        if actual.model:
            parts.append(f"Model: {actual.model}\n")

        parts.append(
            f"\n## Inputs\n\n```json\n{json.dumps(actual.inputs, indent=2, default=str)}\n```\n"
        )
        parts.append(
            f"\n## Outputs\n\n```json\n{json.dumps(actual.outputs, indent=2, default=str)}\n```\n"
        )
        if expected is not None:
            parts.append(
                "\n## Expected outputs (reference)\n\n"
                f"```json\n{json.dumps(expected.outputs, indent=2, default=str)}\n```\n"
            )
        return "".join(parts)

    # ─── Internal: API call + cost ───────────────────────────────────────

    def _get_client(self) -> Any:
        """Lazy-load the Anthropic client. Cached on first use."""
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise ImportError(
                    "LlmJudgeScorer requires the 'llm-judge' extra. "
                    "Install with: pip install 'pipewise[llm-judge]'"
                ) from e
            kwargs: dict[str, Any] = {"max_retries": self.max_retries}
            if self._api_key is not None:
                kwargs["api_key"] = self._api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def _call_judge(
        self,
        system_blocks: list[dict[str, Any]],
        user_message: str,
    ) -> tuple[dict[str, Any], float]:
        """Make one judge call. Returns (verdict_dict, cost_usd)."""
        client = self._get_client()
        response = client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user_message}],
            output_format=_JudgeVerdict,
        )
        verdict: _JudgeVerdict = response.parsed_output
        cost = self._calculate_cost(response.usage)
        return (
            {
                "score": verdict.score,
                "passed": verdict.passed,
                "reasoning": verdict.reasoning,
            },
            cost,
        )

    def _calculate_cost(self, usage: Any) -> float:
        """Convert token counts in `usage` to USD using the model's pricing."""
        pricing = _PRICING.get(self.model)
        if pricing is None:
            pricing = _PRICING[self.DEFAULT_MODEL]

        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

        cost = 0.0
        cost += input_tokens / 1_000_000 * pricing["input"]
        cost += output_tokens / 1_000_000 * pricing["output"]
        cost += cache_read / 1_000_000 * pricing["cache_read"]
        cost += cache_write / 1_000_000 * pricing["cache_write_5m"]
        return cost

    def _check_cost_ceiling(self, *, call_index: int) -> None:
        if self.cost_ceiling_usd is None:
            return
        if self._cumulative_cost_usd >= self.cost_ceiling_usd:
            raise CostCeilingExceeded(
                f"LlmJudgeScorer cumulative cost ${self._cumulative_cost_usd:.4f} "
                f">= ceiling ${self.cost_ceiling_usd:.2f} "
                f"(blocking consensus call {call_index + 1}/{self.consensus_n}). "
                f"Reset with .reset_cost() or raise the ceiling."
            )

    # ─── Internal: aggregation ───────────────────────────────────────────

    def _aggregate(self, verdicts: list[dict[str, Any]]) -> ScoreResult:
        n = len(verdicts)
        passed_count = sum(1 for v in verdicts if v["passed"])
        majority_threshold = (n // 2) + 1
        passed = passed_count >= majority_threshold
        avg_score = sum(v["score"] for v in verdicts) / n
        scorer_cost = sum(v["cost_usd"] for v in verdicts)

        if n == 1:
            reasoning = verdicts[0]["reasoning"]
        else:
            lines = [
                f"Consensus: {passed_count}/{n} judges voted pass "
                f"(threshold: {majority_threshold}).",
                "",
            ]
            for i, v in enumerate(verdicts, start=1):
                lines.append(
                    f"Judge {i} (passed={v['passed']}, score={v['score']}): {v['reasoning']}"
                )
            reasoning = "\n".join(lines)

        return ScoreResult(
            status="passed" if passed else "failed",
            score=avg_score,
            reasoning=reasoning,
            metadata={
                "model": self.model,
                "consensus_n": n,
                "passed_count": passed_count,
                "majority_threshold": majority_threshold,
                "individual_verdicts": verdicts,
                "scorer_cost_usd": scorer_cost,
                "cumulative_cost_usd": self._cumulative_cost_usd,
            },
        )


__all__ = [
    "CostCeilingExceeded",
    "LlmJudgeScorer",
]
