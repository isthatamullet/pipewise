# Writing a pipewise adapter

This guide walks through building a pipewise adapter using the two reference integrations as worked examples — a linear-ish 7-step pipeline (FactSpark, news analysis) and a branching/conditional pipeline (resume-tailor). Both adapters are about ~250 lines of Python with full test coverage; you should be able to ship one for your own pipeline in an afternoon.

## What an adapter does

An adapter is a small Python package that lives **inside the pipeline you want to evaluate** and converts that pipeline's outputs into a `pipewise.PipelineRun`. Pipewise core never imports your pipeline — your adapter imports pipewise.

In one sentence: **your pipeline produces raw outputs, your adapter translates those into canonical `PipelineRun`s, pipewise scores them.** Translation happens in your code, before pipewise ever sees the data.

```
your-pipeline-repo/
└── integrations/
    └── pipewise/
        ├── pyproject.toml             # declares pipewise as a dependency
        ├── README.md
        ├── your_pipeline_pipewise/    # your package
        │   ├── __init__.py
        │   └── adapter.py             # exports load_run + default_scorers
        └── tests/
            └── test_adapter.py
```

## Why the adapter lives in your repo, not in pipewise

This is the architectural commitment that makes pipewise's "general framework" claim verifiable. Your pipeline depends on pipewise (via `pip install pipewise`); pipewise has zero knowledge of your pipeline. A reviewer cloning the pipewise repo sees no traces of any specific pipeline in the core code, and the `examples/` directory only links to external adapter implementations.

It also keeps the dependency graph clean: pipewise stays small (no optional pipeline-specific extras to maintain), and your pipeline can iterate on its adapter without coordinating releases with pipewise.

## The contract

An adapter package exposes two functions at module level:

```python
from pathlib import Path
from pipewise import PipelineRun, StepExecution, RunScorer, StepScorer

def load_run(path: Path) -> PipelineRun:
    """Translate one completed pipeline run on disk into a canonical PipelineRun.

    Called by *your* pipeline runner (or a small materialization script you
    write) — not by pipewise. The output of this function gets serialized
    to one row of a JSONL dataset that `pipewise eval` later consumes.
    See "Where PipelineRun JSONL files come from" below."""

def default_scorers() -> tuple[list[StepScorer], list[RunScorer]]:
    """Return the canonical scorer set for this pipeline. Used by
    `pipewise eval --adapter <module>` when no `--scorers <toml>` is
    supplied. Optional — if your adapter omits `default_scorers`, every
    `pipewise eval` invocation must pass `--scorers <toml>` explicitly."""
```

`load_run` is required; `default_scorers` is optional. Pipewise's `--adapter` flag accepts a dotted module path (e.g., `--adapter factspark_pipewise.adapter`) and resolves `default_scorers` via `importlib.import_module` at eval time. **Pipewise never calls `load_run` itself** — `load_run` is a helper your own code uses to build the JSONL dataset that pipewise consumes.

## Where PipelineRun JSONL files come from

`pipewise eval --dataset <path.jsonl>` consumes a JSONL file where **each line is a complete serialized `PipelineRun`** (not a path or pointer). That JSONL is built upstream of pipewise, by your own code, in four steps:

1. **Your pipeline runs** against your dataset of *inputs* and produces raw outputs (e.g., `articles/<id>_step{N}.json` files for FactSpark, or whatever shape your pipeline emits).
2. **Your runner code calls `adapter.load_run(raw_path)`** for each completed run, getting back a `PipelineRun` object.
3. **Your runner serializes each `PipelineRun` to one line of JSONL** via `run.model_dump_json()` and writes the lines to your golden dataset file.
4. **`pipewise eval --dataset golden.jsonl --adapter <module>`** reads the JSONL, validates each row as a `PipelineRun`, and runs your default scorers (or the ones in `--scorers <toml>` if supplied).

A minimal materialization script — call it `build_dataset.py` and check it into your pipeline repo:

```python
# build_dataset.py — runs once after your pipeline finishes, before pipewise eval
from pathlib import Path
from your_pipeline_pipewise.adapter import load_run

raw_run_paths = sorted(Path("articles/").glob("*_step1.json"))
with Path("golden.jsonl").open("w", encoding="utf-8") as out:
    for path in raw_run_paths:
        run = load_run(path)
        out.write(run.model_dump_json() + "\n")
```

Then:

```bash
pipewise eval --dataset golden.jsonl --adapter your_pipeline_pipewise.adapter
```

This separation has three useful properties:

- **Pipewise never imports or executes your pipeline code at eval time.** It only imports your adapter module to look up `default_scorers`. CI environments running `pipewise eval` don't need your pipeline's runtime dependencies.
- **`golden.jsonl` is a stable, self-contained artifact.** You can commit it to git, hand it to another tool, or eval it with a future version of pipewise without re-running your pipeline.
- **`load_run` failures are debuggable in your own code, not buried in pipewise output.** If your adapter raises, it raises in your runner script, with your stack trace — not inside `pipewise eval`.

## Worked example 1 — FactSpark (linear pipeline)

FactSpark is a 7-step news-analysis pipeline. Each step writes its output as JSON to `articles/<prefix>_step{N}.json`. Steps 1-6 propagate `full_article_content` forward; step 7 (Gemini-based claim verification) has a totally different output schema.

The adapter (~250 LOC at `factspark-app/integrations/pipewise/factspark_pipewise/adapter.py` once that repo flips public alongside pipewise v1.0):

```python
# factspark_pipewise/adapter.py — abridged
_STEP_LINEUP: list[tuple[str, str, str, str]] = [
    ("analyze",            "analyze-article",            "claude-opus-4-7", "anthropic"),
    ("enhance_entities",   "enhance-entities-geographic","claude-opus-4-7", "anthropic"),
    ("enhance_content",    "enhance-content-assessment", "claude-opus-4-7", "anthropic"),
    ("enhance_source",     "enhance-source-temporal",    "claude-opus-4-7", "anthropic"),
    ("stupid_meter",       "stupid-meter",               "claude-opus-4-7", "anthropic"),
    ("enhance_analytics_ui","enhance-analytics-ui",      "claude-opus-4-7", "anthropic"),
    ("verify_claims",      "verify-claims",              "gemini-3.1-pro",  "google"),
]

def load_run(path: Path) -> PipelineRun:
    prefix = Path(str(path)).name.removesuffix("_step1.json")
    articles_dir, step_paths = _find_step_files(prefix)
    base = datetime.fromtimestamp(step_paths[0].stat().st_mtime, tz=UTC)

    steps: list[StepExecution] = []
    for i, ((step_id, executor, model, provider), step_path) in enumerate(
        zip(_STEP_LINEUP, step_paths, strict=True)
    ):
        if not step_path.exists():
            steps.append(StepExecution(
                step_id=step_id, step_name=step_id.replace("_", " ").title(),
                started_at=base + timedelta(seconds=i * 10), completed_at=None,
                status="failed", error=f"step{i + 1}.json missing",
                executor=executor, model=model, provider=provider,
            ))
            continue
        outputs = json.loads(step_path.read_text(encoding="utf-8"))
        steps.append(StepExecution(
            step_id=step_id, step_name=step_id.replace("_", " ").title(),
            started_at=base + timedelta(seconds=i * 10),
            completed_at=base + timedelta(seconds=(i * 10) + 5),
            status="completed", executor=executor, model=model, provider=provider,
            outputs=outputs,
        ))

    return PipelineRun(
        run_id=prefix, pipeline_name="factspark",
        started_at=base, completed_at=base + timedelta(seconds=70),
        status="completed" if all(s.status == "completed" for s in steps) else "partial",
        steps=steps, final_output=steps[-1].outputs,
        adapter_name="factspark-pipewise-adapter", adapter_version="0.1.0",
    )
```

Things worth noting:

- **Stable `step_id`s, not "step_N".** The schema reasons about "did the same step run last time?" via `step_id`, so meaningful names (`analyze`, `verify_claims`) outlive renames in the source pipeline.
- **`executor` matches the source agent's filename stem** — adapter-guide readers and ops folks see the same names in pipewise reports as in `.claude/agents/`.
- **Timestamps are synthesized** because FactSpark doesn't record per-step start times. The adapter uses each step file's mtime as a stand-in. This is a common shape for Claude-Code-orchestrated pipelines (no per-call telemetry; see "Cost capture" below).
- **Mid-run failure is recorded, not raised.** A missing step file becomes `status="failed"` with an `error` message; the run continues and is marked `status="partial"`.

## Worked example 2 — resume-tailor (branching pipeline)

The resume-tailor pipeline is a 7-step Claude Code agent system that tailors a resume to a specific job posting. Compared to FactSpark, it stresses three additional schema-level concerns:

- **Optional steps:** step 2 (discover experience) is sometimes skipped for straightforward roles.
- **Branching / conditional steps:** step 4 (write chronological resume) and step 4b (write hybrid resume) are mutually exclusive — both write to `step4.json`, distinguished by a `resume_format` field.
- **Mixed JSON / Markdown:** steps 1-5 are JSON; step 6 produces cover-letter and application-response Markdown; step 7 (Canva export) has no filesystem output.

The adapter (lives at `job-search/integrations/pipewise/resume_tailor_pipewise/adapter.py` — public alongside pipewise v1.0) records the conditional shape by **always emitting both step IDs** with one marked `status="skipped"`:

```python
# resume_tailor_pipewise/adapter.py — abridged
chronological_taken, _ = _resolve_step4_format(step3, step4)

if chronological_taken:
    steps.append(_make_step(
        step_id="write_resume_chronological",
        step_name="Write Resume (Chronological)",
        executor="resume-step4-write-resume",
        started_at=at(30), duration_s=5, status="completed", outputs=step4,
    ))
    steps.append(_make_step(
        step_id="write_resume_hybrid",
        step_name="Write Resume (Hybrid)",
        executor="resume-step4b-write-resume-hybrid",
        started_at=at(40), duration_s=0, status="skipped",
    ))
else:  # hybrid taken
    steps.append(_make_step(
        step_id="write_resume_chronological",
        step_name="Write Resume (Chronological)",
        executor="resume-step4-write-resume",
        started_at=at(30), duration_s=0, status="skipped",
    ))
    steps.append(_make_step(
        step_id="write_resume_hybrid",
        step_name="Write Resume (Hybrid)",
        executor="resume-step4b-write-resume-hybrid",
        started_at=at(40), duration_s=5, status="completed", outputs=step4,
    ))
```

The two-step-IDs-with-one-skipped pattern is what lets `pipewise diff` surface a format flip between runs as a status change — the most readable kind of regression signal.

For the optional-step case (step 2), the adapter emits a single step entry whose status switches with the source data:

```python
if step2 is None:                           # step2.json absent on disk
    steps.append(_make_step(step_id="discover_experience", status="skipped", ...))
else:
    steps.append(_make_step(step_id="discover_experience", status="completed", outputs=step2, ...))
```

For step 7 (apply_to_canva), the adapter always emits `status="skipped"` because the canonical store is Canva, not the filesystem. This makes the pipeline's true shape visible in pipewise reports — operators reading the report shouldn't have to remember "Canva exists outside our schema."

## The `default_scorers()` contract

`default_scorers()` returns the canonical scorer set used by `pipewise eval` when no `--scorers <toml>` is supplied. Both reference adapters follow the same pattern:

```python
def default_scorers() -> tuple[list[StepScorer], list[RunScorer]]:
    step_scorers: list[StepScorer] = [
        RegexScorer(field="full_article_content", pattern=r".{100,}",
                    name="article-body-present"),
    ]
    run_scorers: list[RunScorer] = [
        CostBudgetScorer(budget_usd=1.0,    on_missing="skip", name="cost-cap"),
        LatencyBudgetScorer(budget_ms=120_000, on_missing="skip", name="latency-cap"),
    ]
    return step_scorers, run_scorers
```

**Convention: exclude `LlmJudgeScorer` from defaults.** It's the only built-in scorer that calls a paid API, and surprise costs hurt UX for first-time users. Power users opt in explicitly via `pipewise eval --scorers <toml>`. (See `docs/scorers.md` for the matching guidance on scorer config files.)

**Convention: pick step-level scorers that produce a meaningful pass/fail signal, not all-pass-or-all-fail.** FactSpark's `article-body-present` regex passes on steps 1-6 (where `full_article_content` propagates) and fails on step 7 (different schema) — six passes plus one fail per run is a real eval signature, and a future regression that breaks propagation surfaces immediately. For the resume-tailor adapter, the equivalent is an adapter-derived `_company` field flattened onto every step's outputs (including skipped ones), which produces an all-pass baseline that catches propagation regressions cleanly.

**Convention: budget scorers use `on_missing="skip"` when cost / latency data isn't available.** Both reference pipelines run inside Claude Code, which doesn't currently expose per-agent usage telemetry to user code — see the "Cost capture status" section in pipewise's README for the full deferral story. Adapters set `cost_usd` / `latency_ms` to `None` and rely on `on_missing="skip"` so the budget scorers register the *intent* without producing fake failures. When telemetry becomes available, the only change needed is `on_missing="fail"`.

## Cost / latency / tokens

Pipewise's schema has first-class fields for cost, latency, and token counts (`StepExecution.cost_usd`, `latency_ms`, `input_tokens`, `output_tokens`, plus run-level totals). When your pipeline captures this data, populate it — the budget scorers and any future cost-aware reporting come along for free.

When your pipeline *doesn't* capture this data (e.g., Claude Code agents in v1), leave those fields as `None` and use `on_missing="skip"` on the budget scorers. Pipewise's schema is forward-compatible: turning the data on later is purely additive — no adapter contract changes, no schema migrations.

## Testing your adapter

Both reference adapters ship with a `tests/test_adapter.py` covering:

- `load_run` against synthetic step files in `tmp_path` (always-runs)
- `load_run` against real pipeline output (skipped when the canonical local data isn't present)
- `default_scorers()` shape: list types, no `LlmJudgeScorer`, budget scorers use `on_missing="skip"`
- End-to-end `run_eval` round-trip against synthetic runs

Pipewise itself ships matching gate tests in `tests/integration/test_phase4_*_gate.py` that drive `pipewise.run_eval` through the production adapters end-to-end on real pipeline data — they skip cleanly on contributor machines without local pipeline data.

## Reference adapters

Both reference adapters ship in their own pipeline repos and go public alongside pipewise v1.0. See [`examples/README.md`](../examples/README.md) for the canonical list, and [`docs/schema.md`](schema.md) for the field-by-field schema reference.

- **FactSpark** — linear-ish 7-step news-analysis pipeline, mixed Anthropic / Google models
- **Resume-tailor** — branching/conditional pipeline with optional steps and Markdown side-products
