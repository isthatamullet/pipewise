# Example integrations

Pipewise is pipeline-agnostic — any multi-step LLM pipeline plugs in via an adapter file. This directory contains reference adapters that exercise the schema against widely-used OSS frameworks.

## Reference adapters

Two reference adapters cover the two major agent-orchestration paradigms. Both ship as in-tree subpackages with their own `pyproject.toml` and dep stack, so pipewise core stays free of adapter dependencies.

| Adapter | Upstream | Paradigm | Location |
|---|---|---|---|
| **`pipewise_langgraph`** | [LangGraph](https://langchain-ai.github.io/langgraph/) `create_react_agent` | Declarative graph orchestration | [`./langgraph/`](./langgraph/) |
| **`pipewise_anthropic_quickstarts`** | [Anthropic Quickstarts `agents`](https://github.com/anthropics/anthropic-quickstarts/tree/main/agents) | Imperative loop orchestration (Anthropic SDK) | [`./anthropic-quickstarts/`](./anthropic-quickstarts/) |

Both adapters demonstrate the same pipewise schema-mapping pattern — adopters can clone either and adapt it to their own production pipeline. The two share an iteration-naming convention (`<step>__N` always-suffixed) and use intentionally identical tools (`calculator` + `lookup_country`) so adopters can compare the two reference implementations side by side.

Each adapter directory has its own README covering the captured sample dataset, the default scorer suite, and how to regenerate captures locally.

## Writing your own adapter

See [`docs/adapter-guide.md`](../docs/adapter-guide.md).
