"""ExactMatchScorer — field-level deep equality on a step's outputs.

Compares one or more fields in `actual.outputs` to `expected.outputs` using
Python's `==` (deep for nested dicts/lists). Useful for golden-output testing
where a step's structured output is supposed to be byte-for-byte stable.

Score is the fraction of fields that matched (e.g., 2 of 3 → 0.66); `passed`
is True iff every requested field matched. The fraction makes regression
reports more informative than a strict 0.0/1.0 — you can see at a glance
"the title still matches, but the summary drifted."
"""

from collections.abc import Sequence
from typing import Any

from pipewise.core.schema import StepExecution
from pipewise.core.scorer import ScoreResult


class ExactMatchScorer:
    """Compares `actual.outputs[field]` to `expected.outputs[field]` per field."""

    def __init__(
        self,
        fields: Sequence[str],
        *,
        name: str | None = None,
    ) -> None:
        if not fields:
            raise ValueError("ExactMatchScorer requires at least one field")
        self.fields: list[str] = list(fields)
        self.name: str = name or f"exact_match[{','.join(self.fields)}]"

    def score(
        self,
        actual: StepExecution,
        expected: StepExecution | None = None,
    ) -> ScoreResult:
        if expected is None:
            raise ValueError("ExactMatchScorer requires an `expected` step to compare against")

        matches: list[str] = []
        mismatches: list[dict[str, Any]] = []
        missing: list[str] = []

        for field in self.fields:
            in_actual = field in actual.outputs
            in_expected = field in expected.outputs
            if not in_actual or not in_expected:
                missing.append(field)
                continue
            if actual.outputs[field] == expected.outputs[field]:
                matches.append(field)
            else:
                mismatches.append(
                    {
                        "field": field,
                        "actual": actual.outputs[field],
                        "expected": expected.outputs[field],
                    }
                )

        total = len(self.fields)
        score_value = len(matches) / total
        passed = len(matches) == total

        reasoning: str | None = None
        if not passed:
            parts: list[str] = []
            if mismatches:
                bad_fields = [m["field"] for m in mismatches]
                parts.append(f"mismatch: {bad_fields}")
            if missing:
                parts.append(f"missing: {missing}")
            reasoning = "; ".join(parts)

        return ScoreResult(
            score=score_value,
            passed=passed,
            reasoning=reasoning,
            metadata={
                "matched_fields": matches,
                "mismatched_fields": mismatches,
                "missing_fields": missing,
            },
        )


__all__ = ["ExactMatchScorer"]
