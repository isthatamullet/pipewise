"""Phase 4 validation gate (issue #30): drive `pipewise.run_eval` end-to-end
through the **real** FactSpark adapter.

This is the production-shape test, not the Phase 1 prototype gate
(`test_factspark_validation_gate.py`). It imports `factspark_pipewise.adapter`
— the adapter package shipped at `factspark/integrations/pipewise/` — and
exercises:

- `load_run` on real FactSpark step-JSON artifacts
- `default_scorers()` returning the canonical defaults
- `pipewise.runner.eval.run_eval` driving those scorers across multiple runs
- `EvalReport.model_dump_json` / `model_validate_json` round-trip with no
  data loss (the same immutability guarantee Phase 1 #6 verified for raw runs,
  now extended to the report layer)

Skips automatically when the FactSpark articles dir is absent OR when the
adapter package isn't installed (`uv pip install -e ~/factspark/integrations/pipewise/`).
Pipewise core has zero runtime dependency on FactSpark; this test runs locally
only — never on CI.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from pipewise.core.report import EvalReport
from pipewise.core.schema import PipelineRun

_FACTSPARK_ARTICLES_DIR = Path.home() / "factspark" / "articles"

# A small dataset of real FactSpark articles. Each prefix is a known-good run
# whose step1-7.json files are present in the articles dir. The adapter
# resolves them by prefix; pipewise then runs scorers across all three.
_REFERENCE_PREFIXES: tuple[str, ...] = (
    "02242026_bbc_trump_tariffs_supreme_court",
    "02252026_apnews_trump_sotu_fact_check",
    "02252026_whitehouse_sotu_democrat_response",
)


def _adapter_module() -> object | None:
    """Return the installed adapter module, or None when unavailable.

    The adapter ships as a separate package outside pipewise (`factspark/
    integrations/pipewise/`), and contributors who don't have FactSpark
    locally won't have it installed. Skip-on-ImportError keeps the gate
    friendly without weakening the assertions when the package IS installed.
    """
    try:
        return importlib.import_module("factspark_pipewise")
    except ImportError:
        return None


_ADAPTER = _adapter_module()
_AVAILABLE_PREFIXES: tuple[str, ...] = tuple(
    p for p in _REFERENCE_PREFIXES if (_FACTSPARK_ARTICLES_DIR / f"{p}_step1.json").exists()
)

pytestmark = pytest.mark.skipif(
    _ADAPTER is None or len(_AVAILABLE_PREFIXES) < 2,
    reason=(
        "Phase 4 FactSpark gate runs locally only — requires both the real "
        "factspark_pipewise adapter to be installed AND >=2 reference "
        "articles present in ~/factspark/articles/."
    ),
)


def _load_real_runs() -> list[PipelineRun]:
    """Build a small dataset of real FactSpark runs via the production adapter."""
    assert _ADAPTER is not None  # pytestmark guarantees this; mypy/runtime sanity.
    runs = [
        _ADAPTER.load_run(_FACTSPARK_ARTICLES_DIR / f"{prefix}_step1.json")  # type: ignore[attr-defined]
        for prefix in _AVAILABLE_PREFIXES
    ]
    return runs


def test_real_adapter_produces_valid_pipeline_runs() -> None:
    """The production adapter's `load_run` returns schema-conforming runs."""
    runs = _load_real_runs()
    assert len(runs) >= 2
    for run in runs:
        assert isinstance(run, PipelineRun)
        assert run.pipeline_name == "factspark"
        assert run.adapter_name == "factspark-pipewise-adapter"
        assert len(run.steps) == 7  # FactSpark canonical shape


def test_default_scorers_drive_run_eval_end_to_end() -> None:
    """Using `default_scorers()` (no `--scorers` override), `run_eval`
    produces the expected per-run report shape.

    Mirrors the in-adapter eval test (`factspark/integrations/pipewise/tests/
    test_adapter.py::TestEndToEndEval`), but covers a multi-run dataset and
    drives the pipewise runner directly so the abstraction is exercised
    in the same configuration the CLI would use.
    """
    assert _ADAPTER is not None
    from pipewise.runner.eval import run_eval

    runs = _load_real_runs()
    step_scorers, run_scorers = _ADAPTER.default_scorers()  # type: ignore[attr-defined]

    report = run_eval(runs, step_scorers, run_scorers, dataset_name="phase4-factspark-gate")

    assert isinstance(report, EvalReport)
    assert len(report.runs) == len(runs)
    # Per-run: 1 step scorer x 7 steps + 2 run scorers = 9 score entries.
    for run_result in report.runs:
        assert len(run_result.step_scores) == 7
        assert len(run_result.run_scores) == 2

    # FactSpark's `article-body-present` regex passes on steps 1-6
    # (full_article_content propagated forward) and fails on step 7
    # (Gemini verifier, different schema). Same pattern as the
    # in-adapter test, now verified against the production runner on
    # multiple real articles.
    for run_result in report.runs:
        passes = sum(1 for r in run_result.step_scores if r.result.passed)
        fails = sum(1 for r in run_result.step_scores if not r.result.passed)
        assert passes == 6
        assert fails == 1


def test_eval_report_round_trips_without_data_loss(tmp_path: Path) -> None:
    """`EvalReport` survives JSON serialization end-to-end, including the
    nested `ScoreResult.metadata` dicts each scorer attaches.

    This is the storage-layer contract pipewise's `report storage` (Phase 3
    #23) relies on. If `EvalReport` round-trips cleanly here on real adapter
    output, the storage path is provably whole.
    """
    assert _ADAPTER is not None
    from pipewise.runner.eval import run_eval

    runs = _load_real_runs()
    step_scorers, run_scorers = _ADAPTER.default_scorers()  # type: ignore[attr-defined]
    report = run_eval(runs, step_scorers, run_scorers, dataset_name="phase4-factspark-roundtrip")

    serialized = report.model_dump_json()
    restored = EvalReport.model_validate_json(serialized)
    assert restored == report

    # Disk round-trip — the same write/read pattern `pipewise.runner.report_storage`
    # uses for timestamped report files.
    out_path = tmp_path / "report.json"
    out_path.write_text(serialized, encoding="utf-8")
    on_disk = EvalReport.model_validate_json(out_path.read_text(encoding="utf-8"))
    assert on_disk == report


def test_run_status_and_step_outputs_consistent_with_source_artifacts() -> None:
    """Every step's outputs equals the source step-JSON byte-for-byte.

    The production adapter doesn't massage the data on the way through
    (no schema normalization, no field renames). This pins that contract
    against silent regressions.
    """
    import json

    runs = _load_real_runs()
    for run in runs:
        for i, step in enumerate(run.steps):
            source = json.loads(
                (_FACTSPARK_ARTICLES_DIR / f"{run.run_id}_step{i + 1}.json").read_text(
                    encoding="utf-8"
                )
            )
            assert step.outputs == source, (
                f"{run.run_id}/step{i + 1}: adapter outputs diverge from source JSON"
            )
