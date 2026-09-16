"""Report identity prevents polygons and republished attributes from moving metrics."""

from __future__ import annotations

import dataclasses

import hypothesis
import hypothesis.strategies

import peri_scribe.incidents
import tests.helpers.strategies.peri_scribe.incidents


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    updates=tests.helpers.strategies.peri_scribe.incidents.update_histories(),
)
def test_reconcile_updates_is_idempotent(
    updates: list[peri_scribe.incidents.IncidentUpdate],
) -> None:
    reconciled = peri_scribe.incidents.reconcile_updates(updates)
    assert peri_scribe.incidents.reconcile_updates(reconciled) == reconciled


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    updates=tests.helpers.strategies.peri_scribe.incidents.update_histories(),
    data=hypothesis.strategies.data(),
)
def test_reconcile_updates_is_independent_of_input_order(
    updates: list[peri_scribe.incidents.IncidentUpdate],
    data: hypothesis.strategies.DataObject,
) -> None:
    reordered = data.draw(hypothesis.strategies.permutations(updates))
    assert peri_scribe.incidents.reconcile_updates(reordered) == (
        peri_scribe.incidents.reconcile_updates(updates)
    )


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    updates=tests.helpers.strategies.peri_scribe.incidents.update_histories(),
)
def test_reconcile_updates_is_unchanged_by_duplicate_reports(
    updates: list[peri_scribe.incidents.IncidentUpdate],
) -> None:
    duplicates = [dataclasses.replace(update) for update in updates]
    assert peri_scribe.incidents.reconcile_updates([*updates, *duplicates]) == (
        peri_scribe.incidents.reconcile_updates(updates)
    )
