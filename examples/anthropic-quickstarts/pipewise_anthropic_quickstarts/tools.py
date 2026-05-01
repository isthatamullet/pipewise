"""Tools used by the reference agent.

Identical in behavior to the LangGraph adapter's tools, but exposed via
Anthropic's tool-call schema instead of LangChain's ``@tool`` decorator. This
parallel is intentional: adopters comparing the two reference adapters see
the *adapter pattern* differ, not the tools themselves.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int | float):
            return float(node.value)
        raise ValueError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        bin_op = _BIN_OPS.get(type(node.op))
        if bin_op is None:
            raise ValueError(f"unsupported binary operator: {type(node.op).__name__}")
        return bin_op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        unary_op = _UNARY_OPS.get(type(node.op))
        if unary_op is None:
            raise ValueError(f"unsupported unary operator: {type(node.op).__name__}")
        return unary_op(_eval_node(node.operand))
    raise ValueError(f"unsupported expression node: {type(node).__name__}")


def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression. Returns result as string."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree.body)
    except (SyntaxError, ValueError, ZeroDivisionError) as exc:
        return f"Error: {exc}"
    if result == int(result):
        return str(int(result))
    return str(result)


_COUNTRIES: dict[str, dict[str, Any]] = {
    "france": {"capital": "Paris", "population": 67_750_000},
    "germany": {"capital": "Berlin", "population": 83_280_000},
    "italy": {"capital": "Rome", "population": 58_990_000},
    "spain": {"capital": "Madrid", "population": 47_780_000},
    "united kingdom": {"capital": "London", "population": 67_330_000},
    "japan": {"capital": "Tokyo", "population": 125_700_000},
    "brazil": {"capital": "Brasilia", "population": 215_300_000},
    "canada": {"capital": "Ottawa", "population": 39_290_000},
    "australia": {"capital": "Canberra", "population": 26_180_000},
    "india": {"capital": "New Delhi", "population": 1_417_000_000},
}


def lookup_country(name: str) -> dict[str, Any]:
    """Look up basic facts about a country."""
    key = name.strip().lower()
    if key not in _COUNTRIES:
        available = sorted(_COUNTRIES.keys())
        return {"error": f"unknown country {name!r}. available: {available}"}
    return dict(_COUNTRIES[key])


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression (+, -, *, /, parens).",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression to evaluate, e.g. '47 * 23 + 100'.",
                },
            },
            "required": ["expression"],
        },
    },
    {
        "name": "lookup_country",
        "description": "Look up basic facts (capital, population) about a country.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Country name, e.g. 'France' or 'Japan'.",
                },
            },
            "required": ["name"],
        },
    },
]


TOOL_EXECUTORS: dict[str, Callable[..., Any]] = {
    "calculator": calculator,
    "lookup_country": lookup_country,
}
