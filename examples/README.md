# Example integrations

> **Status:** Reference adapters land in Phase 4 of the build (see `PLAN.md §6`).

Pipewise's adapter pattern means reference integrations live **inside the pipelines they adapt**, not in this repo. This page is just an index linking out to them.

## Reference adapters (coming in Phase 4)

| Pipeline | Domain | Shape | Adapter location |
|---|---|---|---|
| **FactSpark** | News article analysis | 7 steps, mostly linear, all-JSON | `github.com/isthatamullet/factspark/tree/main/integrations/pipewise` |
| **Resume-tailor** | Job application tailoring | 7 agents, branching + conditional, mixed JSON/Markdown/PDF | `github.com/isthatamullet/tyler/tree/main/integrations/pipewise` |

## Writing your own

See [`docs/adapter-guide.md`](../docs/adapter-guide.md).
