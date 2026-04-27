# Writing a pipewise adapter

> **Status:** Stub. Full guide lands in Phase 1 alongside the schema, with a worked example in Phase 4 alongside the FactSpark and resume-tailor reference adapters.

## What an adapter does

An adapter is a small piece of code that lives **inside the pipeline you want to evaluate** and converts that pipeline's outputs into a `pipewise.PipelineRun`. Pipewise core never imports your pipeline — your adapter imports pipewise.

```
your-pipeline-repo/
  integrations/
    pipewise/
      adapter.py    ← reads your pipeline's output, returns PipelineRun
      golden/       ← hand-curated expected runs
      eval_config.yml
```

## Why the adapter lives in your repo, not in pipewise

This is the architectural commitment that makes pipewise's "general framework" claim verifiable. Your pipeline depends on pipewise (via `pip install pipewise`); pipewise has zero knowledge of your pipeline. A reviewer cloning the pipewise repo sees no traces of any specific pipeline in the core code.

## What the schema looks like (preview)

```python
from pipewise import PipelineRun, StepExecution

run = PipelineRun(
    run_id="...",
    pipeline_name="your-pipeline",
    started_at=...,
    steps=[
        StepExecution(step_id="...", outputs={...}),
        ...
    ],
    adapter_name="your-pipewise-adapter",
    adapter_version="0.1.0",
)
```

Full schema reference will live at `docs/schema.md` once Phase 1 ships.

## Reference adapters

- **FactSpark** — `github.com/isthatamullet/factspark/tree/main/integrations/pipewise` (link goes live after Phase 4)
- **Resume-tailor** — `github.com/isthatamullet/tyler/tree/main/integrations/pipewise` (link goes live after Phase 4)

See `examples/README.md` in this repo for the up-to-date list.
