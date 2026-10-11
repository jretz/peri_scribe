"""Require existing conformance checks to distinguish real, isolated source defects.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

import ast
import dataclasses
import pathlib

import tests.formal.helpers.defect_baselines
import tests.formal.helpers.oracle
import tests.formal.helpers.process


@dataclasses.dataclass(frozen=True, kw_only=True)
class Defect:
    """Identify one production mutation and the established check that must catch it."""

    name: str
    module: str
    function: str
    original: str
    replacement: str
    test: str
    diagnostic: str


DEFECTS = (
    Defect(
        name="transient-checkpoint-rollback",
        module="peri_scribe.fire_updates",
        function="recover_updates",
        original=(
            "peri_scribe.publication.write_state(state_path(year_directory), "
            "pending.state)"
        ),
        replacement=(
            "previous = peri_scribe.publication.read_state("
            "state_path(year_directory), State)\n"
            "    peri_scribe.publication.write_state("
            "state_path(year_directory), pending.state)\n"
            "    if previous is not None:\n"
            "        peri_scribe.publication.write_state("
            "state_path(year_directory), previous)\n"
            "        peri_scribe.publication.write_state("
            "state_path(year_directory), pending.state)"
        ),
        test=(
            "test_journal_recovery.py::"
            "test_create_kmz_real_files_match_checked_crash_prefixes"
        ),
        diagnostic="no compatible TLC execution",
    ),
    Defect(
        name="publication-relative-tolerance-too-wide",
        module="peri_scribe.publication",
        function="mapping_decision",
        original="rel_tol=1e-12,",
        replacement="rel_tol=1e-9,",
        test=(
            "test_numerical_policy.py::"
            "test_mapping_decision_matches_rounded_conversion_and_tolerance_boundaries"
        ),
        diagnostic="assert case.result() == result",
    ),
    Defect(
        name="mixed-geography-generations",
        module="peri_scribe.fires.derived_layers",
        function="authenticated_pair",
        original=(
            "or differential.generation\n"
            "        != peri_scribe.fires.differential.differential_generation(\n"
            "            history_path,\n"
            "            year_directory,\n"
            "        )"
        ),
        replacement="or False",
        test=(
            "test_geography_readers.py::"
            "test_read_derived_layers_matches_checked_generation_decisions"
        ),
        diagnostic="'no compatible TLC event', 'Read'",
    ),
    Defect(
        name="unescaped-source-markdown",
        module="document_text.encoding",
        function="markdown",
        original="return encoded(value, MARKDOWN_RESERVED)",
        replacement="return normalized(value)",
        test=(
            "test_output_text.py::"
            "test_source_text_encodings_match_checked_preservation_contract"
        ),
        diagnostic="source text encoding disagrees with checked reference",
    ),
    Defect(
        name="update-history-tail-before-archive",
        module="peri_scribe.updates",
        function="read_entries",
        original="for component in peri_scribe.log_reading.log_components(path):",
        replacement=(
            "for component in reversed(peri_scribe.log_reading.log_components(path)):"
        ),
        test=(
            "test_update_log_chronology.py::"
            "test_read_entries_and_write_updates_page_match_checked_complete_history"
        ),
        diagnostic="update reader disagrees with checked logical occurrence order",
    ),
    Defect(
        name="invalid-intent-treated-as-missing",
        module="peri_scribe.fire_updates",
        function="read_authoritative",
        original="return document_type.model_validate_json(content)",
        replacement=(
            "try:\n"
            "        return document_type.model_validate_json(content)\n"
            "    except pydantic.ValidationError:\n"
            "        return None"
        ),
        test=(
            "test_durable_update_validation.py::"
            "test_recover_updates_matches_every_checked_validation_path"
        ),
        diagnostic="DID NOT RAISE",
    ),
    Defect(
        name="snapshot-baseline-ignores-current-history-owner",
        module="peri_scribe.updates",
        function="snapshot_from_entries",
        original="identity = history_identity or entry.identity()",
        replacement="identity = entry.identity()",
        test=(
            "test_projected_snapshots.py::"
            "test_snapshot_from_entries_matches_projected_complete_history_reference"
        ),
        diagnostic="assert tuple(observed) == answer",
    ),
    Defect(
        name="source-validation-ignores-coordinate-reference",
        module="peri_scribe.sources.validation",
        function="validate_feed",
        original=(
            "complete_dataframe.crs is None\n"
            "            or complete_dataframe.crs != stored_dataframe.crs"
        ),
        replacement="False",
        test=(
            "test_source_validation.py::"
            "test_validate_feed_matches_checked_relational_coverage_and_diagnostics"
        ),
        diagnostic="assert outcome(result) == answer",
    ),
    Defect(
        name="source-validation-hides-duplicate-rows",
        module="peri_scribe.sources.validation",
        function="duplicate_object_ids",
        original="if count > 1",
        replacement="if count < 0",
        test=(
            "test_source_validation.py::"
            "test_validate_feed_matches_checked_relational_coverage_and_diagnostics"
        ),
        diagnostic="assert outcome(result) == answer",
    ),
    Defect(
        name="log-upper-bound-hides-undated-diagnostics",
        module="peri_scribe.log_reading",
        function="component_lines",
        original="if until is not None and time > until:\n                    continue",
        replacement="if until is not None and time > until:\n                    break",
        test=(
            "test_log_seeking.py::test_seek_since_and_complete_lines_match_proved_reference"
        ),
        diagnostic="assert observed == tuple(",
    ),
    Defect(
        name="undated-history-claim-priority",
        module="peri_scribe.fire_updates",
        function="mapping_priority",
        original="latest is not None,",
        replacement="latest is None,",
        test=(
            "test_identity_transfer.py::"
            "test_resolved_ownership_matches_latest_alias_claims_and_retained_buckets"
        ),
        diagnostic="history without winning claim",
    ),
    Defect(
        name="nonfinite-raw-number",
        module="peri_scribe.geo.parsing",
        function="numeric_value",
        original="return parsed if math.isfinite(parsed) else None",
        replacement="return parsed",
        test="test_raw_decoding.py::test_numeric_value_and_float_attribute_match_lean",
        diagnostic="result(parser(candidate.raw)) == reference",
    ),
    Defect(
        name="monitor-publication-after-stop",
        module="peri_scribe.monitor.session",
        function="publish",
        original="session.owner.stopped.is_set() or snapshot is session.snapshot",
        replacement="snapshot is session.snapshot",
        test=(
            "test_monitor_tasks.py::"
            "test_monitor_session_public_requests_match_tlc_execution"
        ),
        diagnostic="no compatible TLC execution",
    ),
    Defect(
        name="missing-recovery-intent",
        module="peri_scribe.pipeline",
        function="run_fetch_stage",
        original="peri_scribe.pipeline_state.DERIVED_STAGES",
        replacement="()",
        test=(
            "test_fetch_recovery.py::"
            "test_run_fetch_stage_recovers_each_checked_source_interruption_boundary"
        ),
        diagnostic="read_state(directory) == interrupted.pending",
    ),
    Defect(
        name="missing-chart-key-dependency",
        module="peri_scribe.kml.plot_rendering",
        function="plot_key",
        original="request.y_axis_label,",
        replacement='"fixed-axis",',
        test=(
            "test_cache_dependencies.py::"
            "test_product_keys_preserve_declared_dependencies_and_exact_fresh_results"
            "[chart-axis]"
        ),
        diagnostic="actual.hit == bool(same_key)",
    ),
    Defect(
        name="exclusive-score-threshold",
        module="peri_scribe.fires.scoring",
        function="tiered_points",
        original="value >= tier.threshold",
        replacement="value > tier.threshold",
        test="test_scoring.py::test_fire_score_for_matches_lean_at_every_score_tier",
        diagnostic="implementation_score(case) == result[0]",
    ),
    Defect(
        name="ambiguous-source-fields",
        module="peri_scribe.sources.digests",
        function="framed_value",
        original='value.replace(b"\\x00", b"\\x00\\x01") + b"\\x00\\x00"',
        replacement="value",
        test="test_source_digest.py::test_framed_value_matches_proved_byte_encoding",
        diagnostic="== encoded",
    ),
    Defect(
        name="missing-source-schema",
        module="peri_scribe.sources.digests",
        function="dataframe_digest",
        original="*(digest_value(column) for column in attribute_columns),",
        replacement="",
        test=(
            "test_source_digest.py::"
            "test_dataframe_digest_equality_matches_proved_semantic_equivalence"
        ),
        diagnostic="assert (actual[first] == actual[second]) == equal",
    ),
    Defect(
        name="replayed-log-rotation",
        module="peri_scribe.logging",
        function="compress_log",
        original="if recover_rotation(path):",
        replacement="if False:",
        test=(
            "test_log_rotation.py::"
            "test_compress_log_matches_checked_interruption_histories"
        ),
        diagnostic="rotation escaped checked durable states",
    ),
    Defect(
        name="omitted-archive-prefix",
        module="peri_scribe.log_reading",
        function="log_components",
        original="candidates = (archive,) if committed else (archive, plain)",
        replacement=(
            "candidates = (archive,) if committed else "
            "((plain,) if plain.exists() else (archive,))"
        ),
        test=(
            "test_log_readers.py::"
            "test_complete_lines_matches_checked_reader_observations"
        ),
        diagnostic="monthly reader disagrees with the checked observation",
    ),
)


def mutate(source: str, defect: Defect) -> str:
    """Fail on source drift instead of silently testing a missing or misplaced defect.

    Args:
        source: The original production module, copied into private temporary storage.
        defect: The exact mutation within one named module-level function.

    Returns:
        Syntactically valid source with exactly one intended replacement.
    """
    tree = ast.parse(source)
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == defect.function
    ]
    assert len(functions) == 1, defect.name
    function = functions[0]
    lines = source.splitlines(keepends=True)
    body = "".join(lines[function.lineno - 1 : function.end_lineno])
    assert body.count(defect.original) == 1, defect.name
    changed = body.replace(defect.original, defect.replacement, 1)
    result = "".join((
        *lines[: function.lineno - 1],
        changed,
        *lines[function.end_lineno :],
    ))
    ast.parse(result)
    return result


def check(
    defect: Defect,
    directory: pathlib.Path,
    baseline: tests.formal.helpers.defect_baselines.Baseline,
) -> None:
    """A matching pristine success and a semantic mutant failure are both required.

    Args:
        defect: The production behavior to deliberately break.
        directory: A per-test private tree; repository files are never modified.
        baseline: Complete passing evidence for the identical unmodified source tree.
    """
    assert defect.test in baseline.tests
    source = tests.formal.helpers.defect_baselines.source_copy(directory)
    assert tests.formal.helpers.defect_baselines.fingerprints(source) == baseline.files
    module = source.joinpath(*defect.module.split(".")).with_suffix(".py")
    module.write_text(mutate(module.read_text(), defect))
    rejected = tests.formal.helpers.process.run(
        tests.formal.helpers.defect_baselines.command(
            source,
            directory,
            (
                tests.formal.helpers.defect_baselines.Target(
                    module=defect.module,
                    test=defect.test,
                ),
            ),
        ),
        cwd=tests.formal.helpers.oracle.DIRECTORY.parents[1],
        timeout=180,
    )
    diagnostics = rejected.stdout + rejected.stderr
    assert rejected.returncode == 1, diagnostics
    assert "1 failed" in rejected.stdout, diagnostics
    assert "ERROR collecting" not in diagnostics, diagnostics
    assert "tests/formal/helpers/tlc.py:" not in diagnostics, diagnostics
    assert "tests/formal/helpers/oracle.py:" not in diagnostics, diagnostics
    assert defect.test in diagnostics, diagnostics
    assert defect.diagnostic in diagnostics, diagnostics
