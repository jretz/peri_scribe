"""Protect historical reconstruction from missing identifiers and build evidence."""

import datetime
import json
import pathlib
import unittest.mock

import pandas as pd
import pytest

import migrations.backfill_fire_updates
import migrations.backfill_test_support
import peri_scribe.fire_updates


def test_available_history_recovers_mixed_nullable_source_identifiers() -> None:
    """Source availability must survive pandas coercing a missing ID to NaN."""
    collection = migrations.backfill_test_support.captured_mappings()
    result = migrations.backfill_fire_updates.available_history(
        migrations.backfill_test_support.nullable_history(),
        collection,
        perimeters=True,
    )
    pd.testing.assert_series_equal(
        result["available_at"],
        pd.Series(
            pd.to_datetime(["2026-09-19", "2026-09-18"], utc=True),
            name="available_at",
        ),
    )


def test_main_without_successful_builds_preserves_existing_outputs(
    tmp_path: pathlib.Path,
) -> None:
    """An incomplete input copy must not replace a previously staged checkpoint."""
    output = tmp_path / "output"
    artifacts = {
        "derived/fire_updates_state.json": b'{"checkpoint": "preserve"}\n',
        "derived/fire_updates_backfill.json": b'{"audit": "preserve"}\n',
        "logs/2026-09-fire-updates.jsonl": b'{"name": "Timber"}\n',
    }
    for filename, content in artifacts.items():
        path = output / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = migrations.backfill_test_support.output_files(output)
    result = migrations.backfill_test_support.invoke_backfill(
        tmp_path,
        migrations.backfill_test_support.history_inputs([]),
    )
    after = migrations.backfill_test_support.output_files(output)
    if after != before:
        pytest.fail("Backfill without successful builds changed staged output files")
    if result.exit_code == 0 or "No successful KMZ builds" not in result.output:
        pytest.fail(f"Expected an explicit Click error, got: {result.output!r}")


def test_main_without_successful_builds_does_not_create_outputs(
    tmp_path: pathlib.Path,
) -> None:
    """Rejecting empty evidence must leave a missing destination absent."""
    result = migrations.backfill_test_support.invoke_backfill(
        tmp_path,
        migrations.backfill_test_support.history_inputs([]),
    )
    if (tmp_path / "output").exists():
        pytest.fail("Backfill without successful builds created an output directory")
    if result.exit_code == 0 or "No successful KMZ builds" not in result.output:
        pytest.fail(f"Expected an explicit Click error, got: {result.output!r}")


def test_main_with_successful_build_can_publish_an_empty_history(
    tmp_path: pathlib.Path,
) -> None:
    """A real completed build can establish a valid baseline without any perimeters."""
    completed = datetime.datetime(2026, 9, 20, tzinfo=datetime.UTC)
    result = migrations.backfill_test_support.invoke_backfill(
        tmp_path,
        migrations.backfill_test_support.history_inputs([
            migrations.backfill_fire_updates.Build(
                cutoff=completed,
                completed=completed,
            ),
        ]),
    )
    if result.exit_code != 0:
        pytest.fail(f"Valid build failed: {result.output!r} ({result.exception!r})")
    output = tmp_path / "output"
    checkpoint = peri_scribe.fire_updates.State.model_validate_json(
        peri_scribe.fire_updates.state_path(output).read_bytes(),
    )
    if checkpoint != peri_scribe.fire_updates.State():
        pytest.fail(f"Unexpected empty-history checkpoint: {checkpoint}")
    audit = json.loads((output / "derived/fire_updates_backfill.json").read_text())
    if audit["successful_kmz_builds"] != 1 or audit["records"] != 0:
        pytest.fail(f"Unexpected empty-history audit: {audit}")


@pytest.mark.parametrize(
    ("perimeter_days", "limit", "covered", "replayed", "last_replayed", "complete"),
    [
        ((1, 2, 3), 1, 1, 1, 1, False),
        ((1, 3), 1, 2, 1, 1, False),
        ((1,), 1, 3, 1, 1, True),
        ((1, 2, 3), None, 3, 3, 3, True),
        ((1, 2, 3), 3, 3, 3, 3, True),
        ((), 1, 3, 0, None, True),
        ((2, 3), 1, 2, 1, 2, False),
    ],
)
def test_main_audit_distinguishes_replay_coverage_from_input_bounds(
    tmp_path: pathlib.Path,
    *,
    perimeter_days: tuple[int, ...],
    limit: int | None,
    covered: int,
    replayed: int,
    last_replayed: int | None,
    complete: bool,
) -> None:
    """The audit must identify which successful builds its checkpoint covers."""
    inputs = migrations.backfill_test_support.replay_inputs(perimeter_days)
    arguments = () if limit is None else ("--limit", str(limit))
    with unittest.mock.patch.object(
        migrations.backfill_fire_updates,
        "prepare_build",
        side_effect=[
            migrations.backfill_test_support.prepared_build(inputs.builds[day - 1])
            for day in perimeter_days
        ],
    ):
        result = migrations.backfill_test_support.invoke_backfill(
            tmp_path,
            inputs,
            arguments,
        )
    if result.exit_code != 0:
        pytest.fail(f"Replay failed: {result.output!r} ({result.exception!r})")
    output = tmp_path / "output"
    audit = json.loads((output / "derived/fire_updates_backfill.json").read_text())
    expected = {
        "successful_kmz_builds": 3,
        "covered_successful_kmz_builds": covered,
        "replayed_builds_with_new_perimeters": replayed,
        "input_first_completed": inputs.builds[0].completed.isoformat(),
        "input_last_completed": inputs.builds[-1].completed.isoformat(),
        "first_completed": inputs.builds[0].completed.isoformat(),
        "last_completed": inputs.builds[covered - 1].completed.isoformat(),
        "last_replayed_completed": (
            inputs.builds[last_replayed - 1].completed.isoformat()
            if last_replayed is not None
            else None
        ),
        "limit": limit,
        "complete": complete,
    }
    if {key: audit.get(key) for key in expected} != expected:
        pytest.fail(f"Incorrect replay coverage: {audit}; expected {expected}")
    checkpoint = peri_scribe.fire_updates.State.model_validate_json(
        peri_scribe.fire_updates.state_path(output).read_bytes(),
    )
    expected_perimeters = (
        {"Timber": frozenset({inputs.builds[last_replayed - 1].completed.isoformat()})}
        if last_replayed is not None
        else {}
    )
    if checkpoint.perimeters != expected_perimeters:
        pytest.fail(f"Checkpoint does not match its replay boundary: {checkpoint}")


def test_backfill_audit_counts_a_renamed_fire_once(tmp_path: pathlib.Path) -> None:
    """Audit identity counts must agree with the history shown by the update viewer."""
    inputs = migrations.backfill_test_support.replay_inputs((1, 2, 3))
    records: list[dict[str, object]] = [
        {
            "timestamp": build.completed.isoformat(),
            "identifier": None,
            "name": name,
            "location": "21 mi SW of Soledad, CA",
            "mapped_area": {"value": 1234.5, "units": "acre"},
            "log_identity": ["name", "Timber"],
        }
        for build, name in zip(
            inputs.builds,
            ["Timber", "Timber Complex", "Timber"],
            strict=True,
        )
    ]
    with unittest.mock.patch.object(
        migrations.backfill_fire_updates,
        "input_checksums",
        return_value={},
    ):
        audit = migrations.backfill_fire_updates.backfill_audit(
            tmp_path,
            inputs,
            records,
            inputs.builds,
            peri_scribe.fire_updates.State(),
            covered=inputs.builds,
            limit=None,
        )
    if audit["distinct_fires"] != 1:
        pytest.fail(f"A renamed fire was counted more than once: {audit}")
