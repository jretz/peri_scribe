"""The hierarchy represents every enum and each independent source instance."""

import typing

import pytest

import peri_scribe.phases
import peri_scribe.pipeline_stages
import tests.helpers.factories.peri_scribe.monitor.events


def test_planned_paths_reaches_every_declared_phase() -> None:
    paths = tuple(
        path
        for gated in (True, False)
        for path in peri_scribe.phases.planned_paths(
            tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
            gated=gated,
        )
    )
    assert {path[-1].phase for path in paths} == {
        *peri_scribe.phases.Phase,
        *peri_scribe.pipeline_stages.Stage,
    }


def test_planned_paths_separates_each_feed() -> None:
    paths = peri_scribe.phases.planned_paths(
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
        gated=True,
    )
    assert {
        path[-1].branch
        for path in paths
        if path[-1].phase == peri_scribe.phases.Phase.COLLECT_FEED
    } == {"alpha", "beta"}


@pytest.mark.parametrize("gated", [False, True])
def test_planned_paths_prepares_boundaries_before_indexing(*, gated: bool) -> None:
    paths = peri_scribe.phases.planned_paths(
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
        gated=gated,
    )
    boundary_paths = [
        path
        for path in paths
        if path[-1].phase == peri_scribe.phases.Phase.ADMINISTRATIVE_BOUNDARIES
    ]
    parent = (
        (
            peri_scribe.phases.Segment(phase=peri_scribe.pipeline_stages.Stage.FETCH),
            peri_scribe.phases.Segment(phase=peri_scribe.phases.Phase.DEFERRED_FETCH),
        )
        if gated
        else (
            peri_scribe.phases.Segment(phase=peri_scribe.pipeline_stages.Stage.FETCH),
        )
    )
    boundary = (
        *parent,
        peri_scribe.phases.Segment(
            phase=peri_scribe.phases.Phase.ADMINISTRATIVE_BOUNDARIES,
        ),
    )
    index = (
        *parent,
        peri_scribe.phases.Segment(phase=peri_scribe.phases.Phase.SOURCE_INDEX),
    )
    query = (
        *boundary,
        peri_scribe.phases.Segment(phase=peri_scribe.phases.Phase.QUERY_FEATURES),
    )
    assert boundary_paths == [boundary]
    assert paths.index(boundary) < paths.index(query) < paths.index(index)


def test_planned_paths_retains_generic_branches_without_configuration() -> None:
    assert peri_scribe.phases.planned_paths(peri_scribe.phases.Branches(), gated=False)


def test_phase_catalogue_cannot_be_mutated() -> None:
    with pytest.raises(TypeError):
        typing.cast(
            "dict[object, object]",
            peri_scribe.phases.CHILDREN,
        )[peri_scribe.phases.Phase.READ_SOURCES] = ()
