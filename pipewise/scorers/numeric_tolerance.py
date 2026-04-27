"""NumericToleranceScorer — pass when |actual - expected| ≤ tolerance.

Direct example: FactSpark's `stupidity_rating` shifts by ~15 points across
articles after upstream prompt changes; `NumericToleranceScorer(field=...,
tolerance=10)` would catch that regression on the next CI run.

Two modes:
- absolute (default): pass iff `|actual - expected| <= tolerance`
- relative: pass iff `|actual - expected| / |expected| <= tolerance`,
  where tolerance is interpreted as a fraction (e.g., `tolerance=0.1` for ±10%).
"""

from typing import Any

from pipewise.core.schema import StepExecution
from pipewise.core.scorer import ScoreResult


def _is_real_number(value: Any) -> bool:
    """True for int/float, False for bool (which is technically int) or anything else."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class NumericToleranceScorer:
    """Pass when a numeric field is within tolerance of expected."""

    def __init__(
        self,
        field: str,
        tolerance: float,
        *,
        relative: bool = False,
        name: str | None = None,
    ) -> None:
        if not field:
            raise ValueError("NumericToleranceScorer requires a non-empty field name")
        if tolerance < 0:
            raise ValueError("tolerance must be non-negative")
        self.field = field
        self.tolerance = tolerance
        self.relative = relative
        mode_tag = "rel" if relative else "abs"
        self.name = name or f"numeric_tolerance[{field},{mode_tag}={tolerance}]"

    def score(
        self,
        actual: StepExecution,
        expected: StepExecution | None = None,
    ) -> ScoreResult:
        if expected is None:
            raise ValueError(
                "NumericToleranceScorer requires an `expected` step to compare against"
            )

        if self.field not in actual.outputs:
            return self._fail(f"field '{self.field}' missing from actual.outputs")
        if self.field not in expected.outputs:
            return self._fail(f"field '{self.field}' missing from expected.outputs")

        actual_val = actual.outputs[self.field]
        expected_val = expected.outputs[self.field]

        if not _is_real_number(actual_val):
            return self._fail(
                f"actual.outputs['{self.field}'] is {type(actual_val).__name__}, not a number"
            )
        if not _is_real_number(expected_val):
            return self._fail(
                f"expected.outputs['{self.field}'] is {type(expected_val).__name__}, not a number"
            )

        delta = abs(actual_val - expected_val)

        if self.relative:
            if expected_val == 0:
                # Relative tolerance is undefined when expected is 0; the only
                # safe semantic is "exact match required."
                passed = actual_val == 0
                ratio: float | None = None if actual_val == 0 else float("inf")
            else:
                ratio = delta / abs(expected_val)
                passed = ratio <= self.tolerance
        else:
            ratio = None
            passed = delta <= self.tolerance

        reasoning: str | None = None
        if not passed:
            if self.relative:
                reasoning = (
                    f"|{actual_val} - {expected_val}| / |{expected_val}| = "
                    f"{ratio} > tolerance {self.tolerance}"
                )
            else:
                reasoning = (
                    f"|{actual_val} - {expected_val}| = {delta} > tolerance {self.tolerance}"
                )

        return ScoreResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            reasoning=reasoning,
            metadata={
                "actual": actual_val,
                "expected": expected_val,
                "delta": delta,
                "ratio": ratio,
                "tolerance": self.tolerance,
                "mode": "relative" if self.relative else "absolute",
            },
        )

    def _fail(self, reasoning: str) -> ScoreResult:
        return ScoreResult(
            score=0.0,
            passed=False,
            reasoning=reasoning,
            metadata={
                "tolerance": self.tolerance,
                "mode": "relative" if self.relative else "absolute",
            },
        )


__all__ = ["NumericToleranceScorer"]
