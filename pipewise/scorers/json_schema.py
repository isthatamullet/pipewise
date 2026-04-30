"""JsonSchemaScorer — validate a step's outputs against a JSON Schema document.

Compiles the schema once at construction so the same scorer can be applied
across many steps without per-call schema check cost. Reasoning lists up to
the first 5 validation errors with their JSON-pointer paths so debugging a
regression doesn't require running the validator manually.
"""

from collections.abc import Sequence
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for

from pipewise.core.schema import StepExecution
from pipewise.core.scorer import ScoreResult

_MAX_ERRORS_IN_REASONING = 5


class JsonSchemaScorer:
    """Validate `actual.outputs` against a JSON Schema document."""

    def __init__(
        self,
        schema: dict[str, Any],
        *,
        name: str | None = None,
        applies_to_step_ids: Sequence[str] | None = None,
    ) -> None:
        validator_cls = validator_for(schema, default=Draft202012Validator)
        # Surface schema-level bugs (typo'd keywords, malformed `type`) at
        # construction time rather than on the first scoring call.
        validator_cls.check_schema(schema)
        self.schema = schema
        self.validator = validator_cls(schema)
        self.name = name or "json_schema"
        self.applies_to_step_ids: Sequence[str] | None = (
            tuple(applies_to_step_ids) if applies_to_step_ids is not None else None
        )

    def score(
        self,
        actual: StepExecution,
        expected: StepExecution | None = None,
    ) -> ScoreResult:
        errors = list(self.validator.iter_errors(actual.outputs))
        passed = not errors

        reasoning: str | None = None
        if errors:
            messages: list[str] = []
            for err in errors[:_MAX_ERRORS_IN_REASONING]:
                path = ".".join(str(p) for p in err.absolute_path) or "<root>"
                messages.append(f"{path}: {err.message}")
            if len(errors) > _MAX_ERRORS_IN_REASONING:
                messages.append(f"... {len(errors) - _MAX_ERRORS_IN_REASONING} more")
            reasoning = "; ".join(messages)

        return ScoreResult(
            status="passed" if passed else "failed",
            score=1.0 if passed else 0.0,
            reasoning=reasoning,
            metadata={"error_count": len(errors)},
        )


__all__ = ["JsonSchemaScorer"]
