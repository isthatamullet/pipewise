"""Schema tests for `PipelineRun` and `StepExecution`.

Validates the schema's contract — required fields, enum constraints, non-negative
numeric constraints, datetime tz policy, extra-field policy, round-trip JSON +
dict serialization, and expressiveness against the two reference pipeline shapes
(FactSpark linear, resume-tailor branching) — without requiring access to either
reference pipeline's actual data.

The "validates against real JSON" gates live in issues #6 and #7.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pipewise import PipelineRun, StepExecution, StepStatus

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _step(
    step_id: str = "s1",
    status: StepStatus = "completed",
    started_at: datetime | None = None,
) -> StepExecution:
    """Tiny helper for test fixtures — completed status uses NOW + 1s as completed_at."""
    started = started_at or NOW
    return StepExecution(
        step_id=step_id,
        step_name=step_id.replace("_", " ").title(),
        started_at=started,
        completed_at=started + timedelta(seconds=1) if status == "completed" else None,
        status=status,
    )


class TestStepExecution:
    def test_minimal_valid(self) -> None:
        # status='skipped' has no completed_at requirement, so this is the
        # smallest valid step.
        step = StepExecution(step_id="s1", step_name="S1", started_at=NOW, status="skipped")
        assert step.step_id == "s1"
        assert step.completed_at is None
        assert step.inputs == {}
        assert step.outputs == {}
        assert step.metadata == {}
        assert step.input_tokens is None

    def test_all_fields_set(self) -> None:
        step = StepExecution(
            step_id="analyze",
            step_name="Analyze",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=2),
            status="completed",
            error=None,
            executor="analyze-article",
            model="claude-opus-4-7",
            provider="anthropic",
            inputs={"url": "https://example.com"},
            outputs={"title": "Example", "nested": {"deep": [1, 2, 3]}},
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.01,
            latency_ms=1500,
            metadata={"adapter_specific": "value"},
        )
        assert step.executor == "analyze-article"
        assert step.cost_usd == 0.01
        assert step.outputs["nested"]["deep"] == [1, 2, 3]

    def test_missing_required_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepExecution(  # type: ignore[call-arg]
                step_id="x",
                step_name="X",
                # missing started_at
                status="completed",
            )

    def test_invalid_status_rejected(self) -> None:
        # Arbitrary unknown status string — not in the StepStatus literal.
        with pytest.raises(ValidationError):
            StepExecution(
                step_id="x",
                step_name="X",
                started_at=NOW,
                status="not-a-real-status",  # type: ignore[arg-type]
            )

    def test_running_status_rejected(self) -> None:
        # 'running' was dropped in Phase 1 — pipewise EVALUATES completed runs,
        # not in-flight ones (PLAN.md §7 D8).
        with pytest.raises(ValidationError):
            StepExecution(
                step_id="x",
                step_name="X",
                started_at=NOW,
                status="running",  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("input_tokens", -1),
            ("output_tokens", -1),
            ("latency_ms", -1),
            ("cost_usd", -0.01),
        ],
    )
    def test_negative_numeric_rejected(self, field: str, value: float) -> None:
        with pytest.raises(ValidationError):
            StepExecution(
                step_id="x",
                step_name="X",
                started_at=NOW,
                completed_at=NOW,
                status="completed",
                **{field: value},  # type: ignore[arg-type]
            )

    def test_zero_numeric_accepted(self) -> None:
        step = StepExecution(
            step_id="x",
            step_name="X",
            started_at=NOW,
            completed_at=NOW,
            status="completed",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        assert step.input_tokens == 0
        assert step.cost_usd == 0.0

    @pytest.mark.parametrize("field", ["step_id", "step_name"])
    def test_empty_required_string_rejected(self, field: str) -> None:
        kwargs: dict[str, object] = {
            "step_id": "x",
            "step_name": "X",
            "started_at": NOW,
            "status": "skipped",
        }
        kwargs[field] = ""
        with pytest.raises(ValidationError):
            StepExecution(**kwargs)  # type: ignore[arg-type]

    def test_extra_field_rejected(self) -> None:
        # B-1 from code review: pin extra-field policy. Adapter authors must
        # use `metadata` for extensions; unknown top-level fields raise loudly.
        with pytest.raises(ValidationError):
            StepExecution(
                step_id="x",
                step_name="X",
                started_at=NOW,
                status="skipped",
                unknown_field="value",  # type: ignore[call-arg]
            )

    def test_naive_datetime_rejected(self) -> None:
        # B-2: timezone-naive datetimes are a footgun for cross-machine /
        # cross-CI portability. Reject them at the boundary.
        naive = datetime(2026, 4, 27, 12, 0, 0)  # no tzinfo
        with pytest.raises(ValidationError):
            StepExecution(
                step_id="x",
                step_name="X",
                started_at=naive,
                status="skipped",
            )

    def test_non_utc_aware_datetime_round_trips(self) -> None:
        # Any tz-aware datetime is allowed; offset must survive round-trip.
        eastern = timezone(timedelta(hours=-5))
        started = datetime(2026, 4, 27, 8, 0, 0, tzinfo=eastern)
        step = StepExecution(
            step_id="x",
            step_name="X",
            started_at=started,
            status="skipped",
        )
        restored = StepExecution.model_validate_json(step.model_dump_json())
        assert restored == step
        # Pydantic preserves the offset; compare as instants to be tz-agnostic.
        assert restored.started_at.utcoffset() == timedelta(hours=-5)

    def test_metadata_accepts_arbitrary_json(self) -> None:
        step = StepExecution(
            step_id="x",
            step_name="X",
            started_at=NOW,
            status="skipped",
            metadata={
                "string": "v",
                "int": 1,
                "float": 1.5,
                "bool": True,
                "none": None,
                "list": [1, 2, 3],
                "nested": {"k": "v"},
            },
        )
        assert step.metadata["nested"]["k"] == "v"
        assert step.metadata["none"] is None

    def test_round_trip_json(self) -> None:
        step = StepExecution(
            step_id="analyze",
            step_name="Analyze",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=5),
            status="completed",
            inputs={"k": 1, "nested": {"deep": [1, 2, 3]}},
            outputs={"result": "ok"},
            input_tokens=100,
            cost_usd=0.001,
        )
        json_str = step.model_dump_json()
        restored = StepExecution.model_validate_json(json_str)
        assert restored == step

    def test_round_trip_python_dict(self) -> None:
        # I-2 #5: dict round-trip exercises a different code path than JSON
        # (datetimes stay as datetime objects, not ISO strings).
        step = StepExecution(
            step_id="analyze",
            step_name="Analyze",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=5),
            status="completed",
            inputs={"k": 1},
            outputs={"r": "ok"},
        )
        as_dict = step.model_dump()
        assert isinstance(as_dict["started_at"], datetime)
        restored = StepExecution.model_validate(as_dict)
        assert restored == step

    def test_extreme_value_round_trip(self) -> None:
        # I-2 #4: Unicode (emoji, RTL), large ints, deeply-nested structures,
        # null in lists — exercises the JSON serializer's edge cases.
        step = StepExecution(
            step_id="extreme",
            step_name="Extreme Values",
            started_at=NOW,
            completed_at=NOW,
            status="completed",
            inputs={
                "emoji": "🚀💥🐍",
                "rtl": "مرحبا بالعالم",
                "large_int": 2**62,
                "small_float": 1e-10,
            },
            outputs={
                "deep": {"a": {"b": {"c": {"d": {"e": [1, None, "x"]}}}}},
                "many_keys": {f"k{i}": i for i in range(100)},
                "null_in_list": [1, None, 2, None],
                "newlines": "line1\nline2\rline3\r\nline4",
                # Smart quotes / em-dash are intentional — testing they round-trip
                # through JSON without mojibake. noqa is for the ambiguous-char
                # warning, which doesn't apply when the chars are the test fixture.
                "smart_quotes": "“curly” ‘ones’ — and an em-dash",  # noqa: RUF001
            },
        )
        json_str = step.model_dump_json()
        restored = StepExecution.model_validate_json(json_str)
        assert restored == step

    def test_completed_status_requires_completed_at(self) -> None:
        # I-3 (narrowed): status='completed' without completed_at is malformed.
        # status='skipped' / 'failed' are not enforced (failed pipelines may
        # genuinely lack an end time).
        with pytest.raises(ValidationError, match="completed_at is required"):
            StepExecution(
                step_id="x",
                step_name="X",
                started_at=NOW,
                status="completed",
                # missing completed_at
            )

    def test_failed_status_allows_missing_completed_at(self) -> None:
        # A real-world case: a step whose source process crashed before
        # recording the end time.
        step = StepExecution(
            step_id="x",
            step_name="X",
            started_at=NOW,
            status="failed",
            error="OOMKilled",
        )
        assert step.completed_at is None


class TestPipelineRun:
    def _minimal_run(self, **overrides: object) -> PipelineRun:
        defaults: dict[str, object] = {
            "run_id": "r1",
            "pipeline_name": "example",
            "started_at": NOW,
            "completed_at": NOW + timedelta(seconds=10),
            "status": "completed",
            "adapter_name": "example-adapter",
            "adapter_version": "0.1.0",
        }
        defaults.update(overrides)
        return PipelineRun(**defaults)  # type: ignore[arg-type]

    def test_minimal_valid(self) -> None:
        run = self._minimal_run()
        assert run.steps == []
        assert run.final_output is None
        assert run.metadata == {}
        assert run.pipeline_version is None

    def test_round_trip_with_many_steps(self) -> None:
        # Reviewer T-2: avoid using exactly 7 (matches both reference pipelines
        # by coincidence, which makes a reader wonder if there's a constraint).
        # 12 steps is just "more than a handful."
        steps = [_step(f"s{i}") for i in range(12)]
        run = self._minimal_run(steps=steps)
        assert len(run.steps) == 12
        assert run.steps[0].step_id == "s0"
        assert run.steps[-1].step_id == "s11"
        # Round-trip preserves order.
        restored = PipelineRun.model_validate_json(run.model_dump_json())
        assert [s.step_id for s in restored.steps] == [s.step_id for s in steps]

    @pytest.mark.parametrize(
        "missing_field",
        ["run_id", "pipeline_name", "started_at", "status", "adapter_name", "adapter_version"],
    )
    def test_missing_required_field_rejected(self, missing_field: str) -> None:
        kwargs: dict[str, object] = {
            "run_id": "r1",
            "pipeline_name": "example",
            "started_at": NOW,
            "status": "completed",
            "completed_at": NOW + timedelta(seconds=10),
            "adapter_name": "example-adapter",
            "adapter_version": "0.1.0",
        }
        del kwargs[missing_field]
        with pytest.raises(ValidationError):
            PipelineRun(**kwargs)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field",
        ["run_id", "pipeline_name", "adapter_name", "adapter_version"],
    )
    def test_empty_required_string_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError):
            self._minimal_run(**{field: ""})

    def test_invalid_status_rejected(self) -> None:
        # Arbitrary unknown status string — not in the RunStatus literal.
        with pytest.raises(ValidationError):
            self._minimal_run(status="bogus")

    @pytest.mark.parametrize(
        "field,value",
        [
            ("total_cost_usd", -1.0),
            ("total_input_tokens", -1),
            ("total_output_tokens", -1),
            ("total_latency_ms", -1),
        ],
    )
    def test_negative_totals_rejected(self, field: str, value: float) -> None:
        with pytest.raises(ValidationError):
            self._minimal_run(**{field: value})

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._minimal_run(unknown_field="value")

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._minimal_run(started_at=datetime(2026, 4, 27, 12, 0, 0))

    def test_completed_status_requires_completed_at(self) -> None:
        with pytest.raises(ValidationError, match="completed_at is required"):
            PipelineRun(
                run_id="r1",
                pipeline_name="example",
                started_at=NOW,
                status="completed",
                # missing completed_at
                adapter_name="x",
                adapter_version="0.1.0",
            )

    def test_partial_status_allows_missing_completed_at(self) -> None:
        # A run that did not finish cleanly may not have a completed_at.
        run = PipelineRun(
            run_id="r1",
            pipeline_name="example",
            started_at=NOW,
            status="partial",
            adapter_name="x",
            adapter_version="0.1.0",
        )
        assert run.completed_at is None

    def test_round_trip_json(self) -> None:
        run = self._minimal_run(
            pipeline_version="1.0.0",
            initial_input={"url": "https://example.com"},
            steps=[_step("analyze")],
            final_output={"summary": "..."},
            total_cost_usd=0.05,
            total_input_tokens=1000,
            total_output_tokens=2000,
            total_latency_ms=30000,
            metadata={"run_metadata": "v"},
        )
        json_str = run.model_dump_json()
        restored = PipelineRun.model_validate_json(json_str)
        assert restored == run

    def test_round_trip_python_dict(self) -> None:
        # See test_round_trip_python_dict for StepExecution — same rationale.
        run = self._minimal_run(steps=[_step("analyze")], metadata={"k": "v"})
        as_dict = run.model_dump()
        assert isinstance(as_dict["started_at"], datetime)
        restored = PipelineRun.model_validate(as_dict)
        assert restored == run

    def test_factspark_shape_round_trips(self) -> None:
        """The schema can express FactSpark's actual run shape:
        7 linear steps, all-Claude except step 7 (Gemini), JSON outputs.

        Shape test only — programmatically constructed, not reading real
        FactSpark JSON. The real-data gate lives in #6.
        """
        step_specs: list[tuple[str, str, str, str]] = [
            ("analyze", "analyze-article", "claude-opus-4-7", "anthropic"),
            ("enhance_entities", "enhance-entities-geographic", "claude-opus-4-7", "anthropic"),
            ("enhance_content", "enhance-content-assessment", "claude-opus-4-7", "anthropic"),
            ("enhance_source", "enhance-source-temporal", "claude-opus-4-7", "anthropic"),
            ("stupid_meter", "stupid-meter", "claude-opus-4-7", "anthropic"),
            ("enhance_analytics_ui", "enhance-analytics-ui", "claude-opus-4-7", "anthropic"),
            ("verify_claims", "verify-claims", "gemini-3.1-pro", "google"),
        ]
        steps = [
            StepExecution(
                step_id=sid,
                step_name=sid.replace("_", " ").title(),
                started_at=NOW + timedelta(seconds=i),
                completed_at=NOW + timedelta(seconds=i + 1),
                status="completed",
                executor=executor,
                model=model,
                provider=provider,
                outputs={"step_n": i + 1},
            )
            for i, (sid, executor, model, provider) in enumerate(step_specs)
        ]
        run = PipelineRun(
            run_id="bbc_trump_tariffs_supreme_court_20260224",
            pipeline_name="factspark",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
            status="completed",
            initial_input={"url": "https://...", "title": "..."},
            steps=steps,
            adapter_name="factspark-pipewise-adapter",
            adapter_version="0.1.0",
        )
        restored = PipelineRun.model_validate_json(run.model_dump_json())
        assert restored == run
        assert restored.steps[-1].provider == "google"
        assert all(s.provider == "anthropic" for s in restored.steps[:-1])

    def test_resume_branching_shape_round_trips(self) -> None:
        """The schema can express the harder resume-tailor pipeline:
        - Step 2 was skipped (status="skipped", no completed_at)
        - Step 4b ran, not Step 4 (branch captured by step_id)
        - Step 7 absent (gated off by step 5 status)

        Shape test only — real-data gate is #7.
        """
        steps = [
            _step("analyze_posting"),
            _step("discovery", status="skipped"),
            _step("research_company"),
            _step("write_resume_hybrid"),  # branch chosen, not "write_resume"
            _step("critique"),
            StepExecution(
                step_id="format_export",
                step_name="Format & Export",
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=1),
                status="completed",
                outputs={"format": "markdown", "ats_risk": "MODERATE"},
            ),
            # step "export_canva" deliberately absent — gated off by step 5
        ]
        run = PipelineRun(
            run_id="deepintent_senior_program_manager",
            pipeline_name="resume-tailor",
            started_at=NOW,
            status="partial",  # gated step means run didn't finish cleanly
            steps=steps,
            adapter_name="resume-tailor-pipewise-adapter",
            adapter_version="0.1.0",
        )
        restored = PipelineRun.model_validate_json(run.model_dump_json())
        assert restored == run
        assert any(s.status == "skipped" for s in restored.steps)
        assert any(s.step_id == "write_resume_hybrid" for s in restored.steps)
        assert not any(s.step_id == "write_resume" for s in restored.steps)
        assert not any(s.step_id == "export_canva" for s in restored.steps)


class TestSchemaPolicies:
    """Policy-level assertions: documented behaviors that consumers can rely on.

    Each test here is the canonical reference for the behavior it documents —
    if the test changes, the schema's contract has changed.
    """

    def test_clock_skew_allowed_step_started_at_after_completed_at(self) -> None:
        """Policy (PLAN.md §7 D13): the schema does NOT enforce
        `started_at <= completed_at`. Reasoning: clock skew across
        distributed systems / CI runners makes strict ordering a frequent
        false-positive that adapters can't always fix at their layer.

        Adapters that DO want strict ordering can validate at their own
        layer; pipewise core stays permissive.
        """
        step = StepExecution(
            step_id="x",
            step_name="X",
            started_at=NOW + timedelta(seconds=10),
            completed_at=NOW,  # earlier than started_at — allowed
            status="completed",
        )
        assert step.completed_at is not None
        assert step.completed_at < step.started_at

    def test_clock_skew_allowed_run_started_at_after_completed_at(self) -> None:
        """Same policy applies at the run level."""
        run = PipelineRun(
            run_id="r1",
            pipeline_name="example",
            started_at=NOW + timedelta(seconds=30),
            completed_at=NOW,
            status="completed",
            adapter_name="x",
            adapter_version="0.1.0",
        )
        assert run.completed_at is not None
        assert run.completed_at < run.started_at

    def test_final_output_is_not_inferred_from_last_step(self) -> None:
        """Policy: `final_output` is a *separate optional field*. Pipewise
        does NOT auto-derive it from `steps[-1].outputs`. PLAN.md §4:
        'Some pipelines have an aggregated final different from the last
        step. Optional.' Adapters that want inference must populate it
        explicitly.
        """
        run = PipelineRun(
            run_id="r1",
            pipeline_name="example",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
            status="completed",
            steps=[
                StepExecution(
                    step_id="last_step",
                    step_name="Last Step",
                    started_at=NOW,
                    completed_at=NOW + timedelta(seconds=5),
                    status="completed",
                    outputs={"key": "step-output-data"},
                ),
            ],
            adapter_name="x",
            adapter_version="0.1.0",
        )
        # No auto-inference: `final_output` is None even though steps[-1] has data.
        assert run.final_output is None

    def test_final_output_explicit_value_preserved(self) -> None:
        """Adapters that DO populate `final_output` get it back unchanged."""
        run = PipelineRun(
            run_id="r1",
            pipeline_name="example",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
            status="completed",
            final_output={"summary": "aggregated", "verdict": "ok"},
            adapter_name="x",
            adapter_version="0.1.0",
        )
        assert run.final_output == {"summary": "aggregated", "verdict": "ok"}

    def test_pipeline_version_optional_default_none(self) -> None:
        """Policy: `pipeline_version` is optional. Pipelines without a
        versioning discipline simply leave it None; PLAN.md §4.5 says
        it tracks 'semver of the pipeline DEFINITION (your prompts)' —
        meaningful only if you do version your prompts.
        """
        run = PipelineRun(
            run_id="r1",
            pipeline_name="example",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
            status="completed",
            adapter_name="x",
            adapter_version="0.1.0",
        )
        assert run.pipeline_version is None

    def test_pipeline_version_explicit_value(self) -> None:
        run = PipelineRun(
            run_id="r1",
            pipeline_name="example",
            pipeline_version="1.2.3",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
            status="completed",
            adapter_name="x",
            adapter_version="0.1.0",
        )
        assert run.pipeline_version == "1.2.3"

    def test_error_field_with_failed_status(self) -> None:
        """Policy: the `error` field is optional and free-form. Adapters
        record whatever message the source pipeline produced — or None
        if it didn't capture one. The schema does not constrain content."""
        step = StepExecution(
            step_id="x",
            step_name="X",
            started_at=NOW,
            status="failed",
            error="OOMKilled: pod evicted at 12:00:00 UTC",
        )
        assert step.error is not None
        assert step.error.startswith("OOMKilled")

    def test_error_field_can_be_none_with_failed_status(self) -> None:
        """A pipeline that crashed before recording an error message is
        a real case (PLAN.md §7 D11). The schema allows error=None on
        a failed step."""
        step = StepExecution(
            step_id="x",
            step_name="X",
            started_at=NOW,
            status="failed",
            # error explicitly None
        )
        assert step.error is None

    def test_empty_steps_list_serializes_correctly(self) -> None:
        """A run with no steps (e.g., a pipeline that crashed before
        starting any step) must serialize cleanly."""
        import json as _json

        run = PipelineRun(
            run_id="r1",
            pipeline_name="example",
            started_at=NOW,
            status="failed",
            adapter_name="x",
            adapter_version="0.1.0",
        )
        serialized = run.model_dump_json()
        # Verify the JSON shape — empty list, not omitted.
        parsed = _json.loads(serialized)
        assert parsed["steps"] == []
        # And round-trips cleanly.
        restored = PipelineRun.model_validate_json(serialized)
        assert restored.steps == []

    def test_totals_are_independent_of_step_values(self) -> None:
        """Policy: run-level `total_*` fields are NOT auto-summed from
        step values. Adapters set them explicitly. This lets adapters
        record values from a source-of-truth (e.g., a billing API)
        rather than re-summing from imperfect step data."""
        run = PipelineRun(
            run_id="r1",
            pipeline_name="example",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
            status="completed",
            steps=[
                StepExecution(
                    step_id="s1",
                    step_name="S1",
                    started_at=NOW,
                    completed_at=NOW + timedelta(seconds=1),
                    status="completed",
                    cost_usd=1.0,
                    input_tokens=10,
                ),
                StepExecution(
                    step_id="s2",
                    step_name="S2",
                    started_at=NOW,
                    completed_at=NOW + timedelta(seconds=1),
                    status="completed",
                    cost_usd=2.0,
                    input_tokens=20,
                ),
            ],
            # Run-level totals NOT 3.0 / 30 — adapter records its own truth.
            total_cost_usd=99.0,
            total_input_tokens=999,
            adapter_name="x",
            adapter_version="0.1.0",
        )
        assert run.total_cost_usd == 99.0
        assert run.total_input_tokens == 999


class TestImports:
    """Verify the top-level re-exports work."""

    def test_top_level_import(self) -> None:
        from pipewise import PipelineRun, RunStatus, StepExecution, StepStatus  # noqa: F401

    def test_core_subpackage_import(self) -> None:
        from pipewise.core import PipelineRun, RunStatus, StepExecution, StepStatus  # noqa: F401
