# Example integrations

Pipewise's adapter pattern means reference integrations live **inside the pipelines they adapt**, not in this repo. This page is just an index pointing at them.

## Reference adapters

Both reference adapters ship in their own pipeline repos and go public alongside pipewise v1.0.

| Pipeline | Domain | Shape | Adapter location |
|---|---|---|---|
| **FactSpark** | News article analysis | 7 steps, linear-ish, all-JSON, mixed Anthropic / Google models | `factspark-app/integrations/pipewise/` |
| **Resume-tailor** | Job application tailoring | 7 agents, branching + conditional, optional steps, mixed JSON / Markdown side-products | `job-search/integrations/pipewise/` |

Both adapters are about ~250 lines of Python with full test coverage. Together they exercise the abstraction across two meaningfully different pipeline shapes — see [`docs/adapter-guide.md`](../docs/adapter-guide.md) for a walkthrough of the conditional-step / branching pattern the resume-tailor adapter uses.

## Writing your own

See [`docs/adapter-guide.md`](../docs/adapter-guide.md).
