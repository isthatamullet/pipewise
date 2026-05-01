"""Construct the canonical ``create_react_agent`` graph used by the adapter.

This is intentionally thin — the adapter's value lies in the *capture* +
*scoring* layer, not in the graph itself. Adopters can swap the LLM by passing
a different ``BaseChatModel`` to :func:`build_react_agent`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.prebuilt import create_react_agent

from .tools import TOOLS

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def build_react_agent(model: BaseChatModel) -> Any:
    """Build a ReAct agent over :data:`pipewise_langgraph.tools.TOOLS`.

    The returned graph has two nodes: ``agent`` (the LLM) and ``tools`` (the
    tool executor). Iteration happens via the agent <-> tools loop; if the
    LLM produces a final answer without invoking any tool, ``tools`` never
    fires and pipewise captures it as ``status="skipped"``.
    """
    return create_react_agent(model, TOOLS)
