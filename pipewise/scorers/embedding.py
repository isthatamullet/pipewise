"""EmbeddingSimilarityScorer — cosine similarity on sentence-transformers embeddings.

Useful for free-text outputs where "semantically equivalent" is the right
comparison rather than character-level equality. Default model is
`all-MiniLM-L6-v2` — small (~80MB), fast, the de-facto industry default
for sentence-level similarity tasks.

The model is lazy-loaded on first `.score()` call so importing the scorer
class doesn't pull in `sentence-transformers` (and its torch dependency,
~2GB). The `[embeddings]` extra in `pyproject.toml` opts users in.
"""

from typing import Any

from pipewise.core.schema import StepExecution
from pipewise.core.scorer import ScoreResult


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 if either is zero-vector."""
    if len(a) != len(b):
        raise ValueError(f"Vectors must be same length (got {len(a)} vs {len(b)})")
    dot: float = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _to_float_list(vec: Any) -> list[float]:
    """Coerce a numpy array, torch tensor, or Python iterable to list[float]."""
    if hasattr(vec, "tolist"):
        return [float(x) for x in vec.tolist()]
    return [float(x) for x in vec]


class EmbeddingSimilarityScorer:
    """Score similarity of `actual.outputs[field]` vs. `expected.outputs[field]`."""

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(
        self,
        field: str,
        *,
        threshold: float = 0.7,
        model_name: str = DEFAULT_MODEL,
        name: str | None = None,
    ) -> None:
        if not field:
            raise ValueError(
                "EmbeddingSimilarityScorer requires a non-empty field name"
            )
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be in [0.0, 1.0]")
        self.field = field
        self.threshold = threshold
        self.model_name = model_name
        self.name = name or f"embedding_similarity[{field}]"
        self._model: Any = None

    def _load_model(self) -> Any:
        """Lazy-load the SentenceTransformer model. Cached after first call.

        Tests can monkeypatch this method to avoid downloading the real model.
        """
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError(
                    "EmbeddingSimilarityScorer requires the 'embeddings' extra. "
                    "Install with: pip install 'pipewise[embeddings]'"
                ) from e
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def score(
        self,
        actual: StepExecution,
        expected: StepExecution | None = None,
    ) -> ScoreResult:
        if expected is None:
            raise ValueError(
                "EmbeddingSimilarityScorer requires an `expected` step to compare against"
            )

        if self.field not in actual.outputs:
            return self._fail(f"field '{self.field}' missing from actual.outputs")
        if self.field not in expected.outputs:
            return self._fail(f"field '{self.field}' missing from expected.outputs")

        actual_text = actual.outputs[self.field]
        expected_text = expected.outputs[self.field]

        if not isinstance(actual_text, str):
            return self._fail(
                f"actual.outputs['{self.field}'] is "
                f"{type(actual_text).__name__}, not str"
            )
        if not isinstance(expected_text, str):
            return self._fail(
                f"expected.outputs['{self.field}'] is "
                f"{type(expected_text).__name__}, not str"
            )

        model = self._load_model()
        embeddings = model.encode([actual_text, expected_text])
        a = _to_float_list(embeddings[0])
        b = _to_float_list(embeddings[1])

        raw_sim = _cosine_similarity(a, b)
        # Clamp to [0, 1]; near-opposite meanings can produce negative cosine,
        # but for similarity scoring we treat that as "completely dissimilar."
        score_value = max(0.0, min(1.0, raw_sim))
        passed = score_value >= self.threshold

        return ScoreResult(
            score=score_value,
            passed=passed,
            reasoning=(
                None
                if passed
                else f"similarity {score_value:.3f} below threshold {self.threshold}"
            ),
            metadata={
                "raw_similarity": raw_sim,
                "threshold": self.threshold,
                "model": self.model_name,
            },
        )

    def _fail(self, reasoning: str) -> ScoreResult:
        return ScoreResult(
            score=0.0,
            passed=False,
            reasoning=reasoning,
            metadata={"threshold": self.threshold, "model": self.model_name},
        )


__all__ = ["EmbeddingSimilarityScorer"]
