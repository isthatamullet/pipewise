"""Unit tests for the calculator and lookup_country tools."""

from __future__ import annotations

import pytest

from pipewise_langgraph.tools import TOOLS, calculator, lookup_country


class TestCalculator:
    def test_basic_arithmetic(self):
        assert calculator.invoke({"expression": "47 * 23 + 100"}) == "1181"

    def test_parentheses(self):
        assert calculator.invoke({"expression": "(2 + 3) * (10 - 4)"}) == "30"

    def test_unary_minus(self):
        assert calculator.invoke({"expression": "-5 + 10"}) == "5"

    def test_floor_division(self):
        assert calculator.invoke({"expression": "10 // 3"}) == "3"

    def test_float_result(self):
        assert calculator.invoke({"expression": "10 / 4"}) == "2.5"

    def test_division_by_zero_returns_error(self):
        result = calculator.invoke({"expression": "10 / 0"})
        assert result.startswith("Error:")

    def test_rejects_function_call(self):
        result = calculator.invoke({"expression": "__import__('os').system('ls')"})
        assert result.startswith("Error: unsupported expression node: Call")

    def test_rejects_attribute_access(self):
        result = calculator.invoke({"expression": "(1).real"})
        assert result.startswith("Error: unsupported expression node:")

    def test_rejects_name(self):
        result = calculator.invoke({"expression": "x + 1"})
        assert result.startswith("Error: unsupported expression node: Name")

    def test_syntax_error(self):
        result = calculator.invoke({"expression": "2 +"})
        assert result.startswith("Error:")


class TestLookupCountry:
    def test_known_country(self):
        result = lookup_country.invoke({"name": "France"})
        assert result["capital"] == "Paris"
        assert result["population"] == 67_750_000

    def test_case_insensitive(self):
        assert lookup_country.invoke({"name": "JAPAN"})["capital"] == "Tokyo"
        assert lookup_country.invoke({"name": "japan"})["capital"] == "Tokyo"

    def test_whitespace_tolerated(self):
        assert lookup_country.invoke({"name": "  India  "})["capital"] == "New Delhi"

    def test_unknown_country_returns_error(self):
        result = lookup_country.invoke({"name": "Atlantis"})
        assert "error" in result
        assert "Atlantis" in result["error"]


def test_tools_collection():
    assert len(TOOLS) == 2
    names = {t.name for t in TOOLS}
    assert names == {"calculator", "lookup_country"}


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("1 + 1", "2"),
        ("100 - 50", "50"),
        ("12 * 12", "144"),
        ("2 ** 10", "1024"),
        ("17 % 5", "2"),
    ],
)
def test_calculator_table(expr: str, expected: str):
    assert calculator.invoke({"expression": expr}) == expected
