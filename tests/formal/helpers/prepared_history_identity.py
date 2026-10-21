"""Connect retained history guards to the complete dependency projection in Lean."""

from __future__ import annotations

import pathlib

import pytest

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.presentation.prepared_cache
import peri_scribe.presentation.text
import spatial_data.product_cache
import tests.formal.helpers.cache_dependencies
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.kml.parsing


def change_history(history: peri_scribe.areas.PreparedHistory, change: str) -> None:
    """Change a complete-history dependency after its payload identity is retained.

    Args:
        history: The independent decoded history held by the active execution.
        change: A measurement, unit, container-order or record-field mutation.
    """
    if change == "measurement":
        history.updates[0].measurements["estimated_cost_to_date"] = 9_000.0
    elif change == "order":
        measurements = history.updates[0].measurements
        assert len(measurements) > 1
        first = next(iter(measurements))
        measurements[first] = measurements.pop(first)
    elif change == "units":
        assert history.latest_area is not None
        history.latest_area.ito("hectare")
    else:
        vars(history)["updates"] = ()


def compare(directory: pathlib.Path, change: str, *, retained: bool) -> None:
    """Check real hits, guard invalidation and exact fresh description bytes.

    The Lean projection independently classifies any complete-history change as a
    required dependency change. Actual mutations happen inside one execution so the
    bridge exercises retained digest guards rather than fresh-scope serialization.

    Args:
        directory: Isolated product storage for this mutation.
        change: One guarded history dependency to change after a real cache hit.
        retained: Whether mutation starts with retained guards or deferred identity.
    """
    contract = tests.formal.helpers.cache_dependencies.DESCRIPTION
    (expected,) = tests.formal.helpers.oracle.evaluate(
        [contract.command("history_units" if change == "units" else "history")],
        executable="oracleCache",
    )
    assert expected == (1, 0, 0)
    perimeters, points = tests.formal.helpers.cache_dependencies.evidence("")
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    original = peri_scribe.areas.prepare_history(perimeters, points)
    payload = peri_scribe.presentation.prepared_cache.history_bytes(original)
    with pytest.MonkeyPatch.context() as monkeypatch:
        accesses = tests.formal.helpers.cache_dependencies.record_reads(
            monkeypatch,
            contract.namespace,
        )
        with (
            peri_scribe.execution.sharing(),
            spatial_data.product_cache.scope(directory / "products.sqlite", "runtime"),
        ):
            history = peri_scribe.presentation.prepared_cache.read_history(payload)
            baseline = peri_scribe.presentation.text.fire_description(
                entry,
                perimeters,
                points,
                history=history,
            )
            assert (
                peri_scribe.presentation.text.fire_description(
                    entry,
                    perimeters,
                    points,
                    history=history,
                )
                == baseline
            )
            cold, warm = accesses
            assert not cold.hit
            assert warm.hit
            assert (cold.context, cold.key) == (warm.context, warm.key)
            if not retained:
                history = peri_scribe.presentation.prepared_cache.read_history(
                    payload,
                    remember_identity=False,
                )
            change_history(history, change)
            changed = peri_scribe.presentation.text.fire_description(
                entry,
                perimeters,
                points,
                history=history,
            )
            actual = accesses[-1]
            assert actual.hit == bool(expected[1])
            assert ((actual.context, actual.key) == (cold.context, cold.key)) == bool(
                expected[1],
            )
        fresh = peri_scribe.presentation.text.fire_description(
            entry,
            perimeters,
            points,
            history=history,
        )
    assert peri_scribe.presentation.prepared_cache.description_bytes(
        changed,
    ) == peri_scribe.presentation.prepared_cache.description_bytes(fresh)
