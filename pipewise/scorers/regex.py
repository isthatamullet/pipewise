"""RegexScorer — regex match against a string field in a step's outputs.

Useful for format checks (date strings, IDs, expected phrases) without
needing a golden expected value. The pattern is compiled once at scorer
construction time so the same scorer can be applied across many steps
without per-call recompile cost.
"""

import re
from collections.abc import Sequence
from typing import Literal

from pipewise.core.schema import StepExecution
from pipewise.core.scorer import ScoreResult

MatchMode = Literal["search", "fullmatch", "match"]


class RegexScorer:
    """Regex match against `actual.outputs[field]`. Self-contained; no expected."""

    def __init__(
        self,
        field: str,
        pattern: str | re.Pattern[str],
        *,
        match_mode: MatchMode = "search",
        name: str | None = None,
        applies_to_step_ids: Sequence[str] | None = None,
    ) -> None:
        if not field:
            raise ValueError("RegexScorer requires a non-empty field name")
        self.field = field
        self.pattern: re.Pattern[str] = re.compile(pattern) if isinstance(pattern, str) else pattern
        self.match_mode: MatchMode = match_mode
        self.name: str = name or f"regex[{field}]"
        self.applies_to_step_ids: Sequence[str] | None = (
            tuple(applies_to_step_ids) if applies_to_step_ids is not None else None
        )

    def score(
        self,
        actual: StepExecution,
        expected: StepExecution | None = None,
    ) -> ScoreResult:
        if self.field not in actual.outputs:
            return ScoreResult(
                status="failed",
                score=0.0,
                reasoning=f"field '{self.field}' missing from outputs",
                metadata={"pattern": self.pattern.pattern, "mode": self.match_mode},
            )

        value = actual.outputs[self.field]
        if not isinstance(value, str):
            return ScoreResult(
                status="failed",
                score=0.0,
                reasoning=(
                    f"field '{self.field}' is {type(value).__name__}, not str — "
                    "regex requires a string value"
                ),
                metadata={"pattern": self.pattern.pattern, "mode": self.match_mode},
            )

        match_fn = getattr(self.pattern, self.match_mode)
        result = match_fn(value)
        passed = result is not None

        return ScoreResult(
            status="passed" if passed else "failed",
            score=1.0 if passed else 0.0,
            reasoning=(
                None
                if passed
                else (
                    f"pattern {self.pattern.pattern!r} did not "
                    f"{self.match_mode} field '{self.field}'"
                )
            ),
            metadata={"pattern": self.pattern.pattern, "mode": self.match_mode},
        )


__all__ = ["MatchMode", "RegexScorer"]
