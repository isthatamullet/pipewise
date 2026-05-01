"""Unit tests for calculator + lookup_country tools."""

from __future__ import annotations

import pytest

from pipewise_anthropic_quickstarts.tools import (
    TOOL_EXECUTORS,
    TOOL_SCHEMAS,
    calculator,
    lookup_country,
)


class TestCalculator:
    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("47 * 23 + 100", "1181"),
            ("(2 + 3) * (10 - 4)", "30"),
            ("-5 + 10", "5"),
            ("10 // 3", "3"),
            ("10 / 4", "2.5"),
            ("2 ** 10", "1024"),
            ("17 % 5", "2"),
        ],
    )
    def test_table(self, expr: str, expected: str):
        assert calculator(expr) == expected

    def test_division_by_zero(self):
        assert calculator("10 / 0").startswith("Error:")

    def test_rejects_function_call(self):
        assert calculator("__import__('os').system('ls')").startswith(
            "Error: unsupported expression node: Call"
        )


class TestLookupCountry:
    def test_known(self):
        assert lookup_country("France")["capital"] == "Paris"

    def test_case_insensitive(self):
        assert lookup_country("JAPAN")["capital"] == "Tokyo"

    def test_unknown(self):
        result = lookup_country("Atlantis")
        assert "error" in result


class TestToolWiring:
    def test_schema_count(self):
        assert len(TOOL_SCHEMAS) == 2
        names = {s["name"] for s in TOOL_SCHEMAS}
        assert names == {"calculator", "lookup_country"}

    def test_executor_count(self):
        assert set(TOOL_EXECUTORS.keys()) == {"calculator", "lookup_country"}

    def test_each_schema_has_executor(self):
        for schema in TOOL_SCHEMAS:
            assert schema["name"] in TOOL_EXECUTORS

    def test_schemas_have_input_schema(self):
        for schema in TOOL_SCHEMAS:
            assert "input_schema" in schema
            assert "type" in schema["input_schema"]
