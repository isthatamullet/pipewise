"""Pipewise reference adapter for Anthropic Quickstarts (`agents`).

Demonstrates pipewise schema coverage of imperative-loop agent orchestration
(Anthropic SDK) — paralleling the LangGraph adapter's declarative-graph
coverage. The included ``MinimalAgent`` mirrors the shape of upstream
``anthropics/anthropic-quickstarts/agents/agent.py`` (which is intentionally
not packaged for install — adopters translate the pattern into their own
code, per upstream's README).

See ``adapter.py`` for the eval-time API surface (``load_run``,
``default_scorers``) and ``capture.py`` for the run-time capture primitive.
"""

__version__ = "0.1.0"
