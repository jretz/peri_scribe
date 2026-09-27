import dataclasses
import datetime
import itertools
import pathlib

import peri_scribe.updates
import tests.formal.helpers.update_viewer


def test_complete_retained_history_selection_matches_lean() -> None:
    histories = tests.formal.helpers.update_viewer.histories()
    assert tests.formal.helpers.update_viewer.compare_histories(histories) == len(
        histories,
    )


def test_browser_current_history_grouping_matches_identity_transfer() -> None:
    cases = tests.formal.helpers.update_viewer.ownership_cases()
    expected_cases = 256
    expected_states = 768
    assert len(cases) == expected_cases
    assert tests.formal.helpers.update_viewer.run_browser(cases) == expected_states


def test_actual_rotated_history_reaches_current_displayed_browser_rows(
    tmp_path: pathlib.Path,
) -> None:
    updates = tests.formal.helpers.update_viewer.retained_snapshot(tmp_path)
    initial = tests.formal.helpers.update_viewer.Step(records=updates)
    replacement = tests.formal.helpers.update_viewer.Step(
        records=tuple(reversed(updates)) + updates,
    )
    case = tests.formal.helpers.update_viewer.browser_case((
        initial,
        replacement,
        initial,
    ))
    assert tests.formal.helpers.update_viewer.run_browser([case]) == len(case)


def test_browser_preserves_duplicate_occurrences_and_signature_reuse() -> None:
    history = (
        tests.formal.helpers.update_viewer.Observation(
            serial=0,
            time=-2,
            name=0,
            area=8,
            identifier=0,
        ),
        tests.formal.helpers.update_viewer.Observation(
            serial=1,
            time=-1,
            name=1,
            area=0,
            identifier=0,
        ),
        tests.formal.helpers.update_viewer.Observation(
            serial=2,
            time=-1,
            name=0,
            area=24,
            identifier=1,
        ),
    )
    updates = peri_scribe.updates.snapshot_from_entries(
        [row.record() for row in history],
        tests.formal.helpers.update_viewer.NOW,
    ).updates
    sequences = [
        sequence
        for length in range(3)
        for sequence in itertools.product(updates, repeat=length)
    ]
    cases = [
        tests.formal.helpers.update_viewer.browser_case((
            tests.formal.helpers.update_viewer.Step(records=old),
            tests.formal.helpers.update_viewer.Step(records=new),
        ))
        for old, new in itertools.product(sequences, repeat=2)
    ]
    assert tests.formal.helpers.update_viewer.run_browser(cases) == sum(map(len, cases))


def test_browser_controls_preserve_rows_counts_and_current_record_mapping() -> None:
    base = peri_scribe.updates.Update(
        **tests.formal.helpers.update_viewer
        .Observation(serial=0, time=-1, name=0, area=16)
        .record()
        .model_dump(),
        previous_mapped_area=peri_scribe.updates.Acreage(value=1),
    )
    records = tuple(
        base.model_copy(
            update={
                "name": tests.formal.helpers.update_viewer.NAMES[
                    index % len(tests.formal.helpers.update_viewer.NAMES)
                ],
                "timestamp": tests.formal.helpers.update_viewer.NOW
                - datetime.timedelta(minutes=age),
                "log_identity": ("local", str(index % 2)),
            },
        )
        for index, age in enumerate((1, 30, 70, 200, 300, 600, 800, 1300, 1500, 2700))
    )
    steps = [tests.formal.helpers.update_viewer.Step(records=records)]
    for bits, query in itertools.product(
        itertools.product((False, True), repeat=5),
        ("", "ALP", "FiRe", "missing"),
    ):
        steps.append(
            tests.formal.helpers.update_viewer.Step(
                records=records,
                query=query,
                name_order=bits,
                collapsed=tuple(not bit for bit in bits),
            ),
        )
    updated = tuple(
        record.model_copy(
            update={
                "mapped_area": peri_scribe.updates.Acreage(value=3),
                "location": "Changed County, NV",
            },
        )
        for record in records
    )
    steps.extend((
        tests.formal.helpers.update_viewer.Step(records=updated),
        tests.formal.helpers.update_viewer.Step(records=records),
    ))
    case = tests.formal.helpers.update_viewer.browser_case(tuple(steps))
    assert tests.formal.helpers.update_viewer.run_browser([case]) == len(case)


def test_browser_timer_crosses_exact_millisecond_bucket_edges() -> None:
    base = peri_scribe.updates.Update(
        **tests.formal.helpers.update_viewer
        .Observation(serial=0, time=-1, name=0, area=8)
        .record()
        .model_dump(),
        previous_mapped_area=None,
    )
    records = tuple(
        base.model_copy(
            update={
                "timestamp": tests.formal.helpers.update_viewer.NOW
                - datetime.timedelta(milliseconds=age + offset),
                "name": tests.formal.helpers.update_viewer.NAMES[
                    index % len(tests.formal.helpers.update_viewer.NAMES)
                ],
                "identifier": str(index),
            },
        )
        for index, (age, offset) in enumerate(
            itertools.product(
                (
                    0,
                    3_600_000,
                    14_400_000,
                    43_200_000,
                    86_400_000,
                    tests.formal.helpers.update_viewer.WINDOW,
                ),
                (-1, 0, 1),
            ),
        )
    )
    initial = tests.formal.helpers.update_viewer.Step(records=records)
    steps = (initial, dataclasses.replace(initial, elapsed=2, timer=True))
    cases = [
        tests.formal.helpers.update_viewer.browser_case(steps),
        tests.formal.helpers.update_viewer.browser_case((
            initial,
            dataclasses.replace(initial, elapsed=1),
        )),
    ]
    assert tests.formal.helpers.update_viewer.run_browser(cases) == sum(map(len, cases))
