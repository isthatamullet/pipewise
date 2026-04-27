"""Tests for `EmbeddingSimilarityScorer`.

Uses a fake model fixture so tests don't need the heavy sentence-transformers
dependency. The lazy-import test exercises the actual ImportError path because
sentence-transformers is intentionally NOT installed in the dev environment
(it's gated behind the `[embeddings]` extra).
"""

import sys
from datetime import UTC, datetime, timedelta

import pytest

from pipewise import StepExecution, StepScorer
from pipewise.scorers.embedding import (
    EmbeddingSimilarityScorer,
    _cosine_similarity,
    _to_float_list,
)

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


class _FakeModel:
    """Stand-in for SentenceTransformer that returns predictable vectors per text."""

    def __init__(self, lookup: dict[str, list[float]]) -> None:
        self.lookup = lookup
        self.encode_calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.encode_calls.append(list(texts))
        return [self.lookup[t] for t in texts]


def _scorer_with_model(
    *,
    field: str = "text",
    threshold: float = 0.7,
    lookup: dict[str, list[float]] | None = None,
) -> tuple[EmbeddingSimilarityScorer, _FakeModel]:
    fake = _FakeModel(lookup or {})
    scorer = EmbeddingSimilarityScorer(field=field, threshold=threshold)
    scorer._model = fake  # bypass lazy load
    return scorer, fake


class TestCosineSimilarityHelper:
    def test_identical_vectors_score_one(self) -> None:
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal_vectors_score_zero(self) -> None:
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_opposite_vectors_score_negative_one(self) -> None:
        assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            _cosine_similarity([1.0], [1.0, 0.0])


class TestToFloatList:
    def test_python_list(self) -> None:
        assert _to_float_list([1, 2, 3]) == [1.0, 2.0, 3.0]

    def test_object_with_tolist(self) -> None:
        class Fake:
            def tolist(self) -> list[int]:
                return [4, 5]

        assert _to_float_list(Fake()) == [4.0, 5.0]


class TestEmbeddingSimilarityScorer:
    def test_satisfies_step_scorer_protocol(self) -> None:
        scorer = EmbeddingSimilarityScorer(field="text")
        assert isinstance(scorer, StepScorer)

    def test_similar_text_scores_high(self) -> None:
        scorer, _ = _scorer_with_model(
            threshold=0.7,
            lookup={
                "Order received": [1.0, 0.0, 0.0],
                "Order placed": [0.95, 0.05, 0.05],
            },
        )
        result = scorer.score(
            _step({"text": "Order received"}),
            _step({"text": "Order placed"}),
        )
        assert result.passed is True
        assert result.score > 0.9

    def test_dissimilar_text_scores_low(self) -> None:
        scorer, _ = _scorer_with_model(
            threshold=0.7,
            lookup={
                "morning coffee": [1.0, 0.0, 0.0],
                "submarine fleet": [0.0, 1.0, 0.0],
            },
        )
        result = scorer.score(
            _step({"text": "morning coffee"}),
            _step({"text": "submarine fleet"}),
        )
        assert result.passed is False
        assert result.score == 0.0
        assert "below threshold" in (result.reasoning or "")

    def test_negative_similarity_clamps_to_zero(self) -> None:
        # Opposite vectors → cosine -1, score clamped to 0.
        scorer, _ = _scorer_with_model(
            lookup={"a": [1.0, 0.0], "b": [-1.0, 0.0]},
        )
        result = scorer.score(_step({"text": "a"}), _step({"text": "b"}))
        assert result.score == 0.0
        assert result.passed is False
        assert result.metadata["raw_similarity"] == -1.0

    def test_threshold_boundary_passes(self) -> None:
        # Construct vectors with cosine = 0.8 exactly: choose a=[1,0], b=[0.8, 0.6]
        # (b is unit vector). dot = 0.8, norms = 1, so cosine = 0.8.
        scorer, _ = _scorer_with_model(
            threshold=0.8,
            lookup={"x": [1.0, 0.0], "y": [0.8, 0.6]},
        )
        result = scorer.score(_step({"text": "x"}), _step({"text": "y"}))
        assert result.passed is True
        assert abs(result.score - 0.8) < 1e-9

    def test_threshold_just_below_fails(self) -> None:
        scorer, _ = _scorer_with_model(
            threshold=0.81,
            lookup={"x": [1.0, 0.0], "y": [0.8, 0.6]},
        )
        result = scorer.score(_step({"text": "x"}), _step({"text": "y"}))
        assert result.passed is False

    def test_missing_actual_field_fails_without_loading_model(self) -> None:
        scorer, fake = _scorer_with_model(lookup={})
        result = scorer.score(_step({}), _step({"text": "anything"}))
        assert result.passed is False
        assert "missing from actual" in (result.reasoning or "")
        assert fake.encode_calls == []

    def test_missing_expected_field_fails(self) -> None:
        scorer, _ = _scorer_with_model(lookup={})
        result = scorer.score(_step({"text": "x"}), _step({}))
        assert result.passed is False
        assert "missing from expected" in (result.reasoning or "")

    def test_non_string_field_fails(self) -> None:
        scorer, _ = _scorer_with_model(lookup={})
        result = scorer.score(_step({"text": 123}), _step({"text": "ok"}))
        assert result.passed is False
        assert "not str" in (result.reasoning or "")

    def test_expected_required(self) -> None:
        scorer = EmbeddingSimilarityScorer(field="text")
        with pytest.raises(ValueError, match="requires an `expected` step"):
            scorer.score(_step({"text": "x"}))

    def test_lazy_import_raises_clear_error_when_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Block the sentence_transformers import via sys.modules so the lazy-load
        # path raises ImportError regardless of whether the package is actually
        # installed locally. Setting the entry to None makes Python raise on import.
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        scorer = EmbeddingSimilarityScorer(field="text")
        with pytest.raises(ImportError, match="embeddings"):
            scorer._load_model()

    def test_model_loaded_only_once(self) -> None:
        """Cached after first load — subsequent score() calls reuse it."""
        scorer, _ = _scorer_with_model(
            lookup={"a": [1.0, 0.0], "b": [1.0, 0.0]},
        )
        original_model = scorer._model
        scorer.score(_step({"text": "a"}), _step({"text": "b"}))
        scorer.score(_step({"text": "a"}), _step({"text": "b"}))
        assert scorer._model is original_model

    def test_invalid_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="threshold"):
            EmbeddingSimilarityScorer(field="x", threshold=1.5)
        with pytest.raises(ValueError, match="threshold"):
            EmbeddingSimilarityScorer(field="x", threshold=-0.1)

    def test_empty_field_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty field"):
            EmbeddingSimilarityScorer(field="")

    def test_default_model_name(self) -> None:
        scorer = EmbeddingSimilarityScorer(field="text")
        assert scorer.model_name == "all-MiniLM-L6-v2"

    def test_custom_model_name(self) -> None:
        scorer = EmbeddingSimilarityScorer(field="text", model_name="other-model")
        assert scorer.model_name == "other-model"

    def test_default_name(self) -> None:
        assert EmbeddingSimilarityScorer(field="text").name == "embedding_similarity[text]"

    def test_custom_name(self) -> None:
        scorer = EmbeddingSimilarityScorer(field="text", name="my_emb")
        assert scorer.name == "my_emb"

    def test_metadata_includes_model_and_threshold(self) -> None:
        scorer, _ = _scorer_with_model(
            threshold=0.5,
            lookup={"a": [1.0, 0.0], "b": [1.0, 0.0]},
        )
        result = scorer.score(_step({"text": "a"}), _step({"text": "b"}))
        assert result.metadata["model"] == "all-MiniLM-L6-v2"
        assert result.metadata["threshold"] == 0.5
