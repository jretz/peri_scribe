"""Complex ownership preserves partial, dated source evidence."""

import dataclasses
import datetime
import pathlib

import pytest

import peri_scribe.fires.complexes
import peri_scribe.models
import tests.helpers.factories.peri_scribe.fires.complexes


@pytest.mark.parametrize("flag", [None, "", "  ", float("nan")])
def test_row_observation_ignores_missing_flags(flag: object) -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history([(0, 1, 1)])
    row = dataclasses.replace(read.rows[-1], attributes={"attr_IsCpxChild": flag})
    assert peri_scribe.fires.complexes.row_observation(row, read.paths[-1]) is None


def test_row_observation_accepts_parent_without_name() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history([(0, 1, 1)])
    attributes = dict(read.rows[-1].attributes)
    attributes.pop("attr_CpxName")
    row = dataclasses.replace(read.rows[-1], attributes=attributes)
    result = peri_scribe.fires.complexes.row_observation(row, read.paths[-1])
    assert result is not None
    assert result.complex_identifier == result.complex_name == "fire-1"


def test_row_observation_requires_parent_for_positive_flag() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history([(0, 1, 1)])
    row = dataclasses.replace(read.rows[-1], attributes={"attr_IsCpxChild": True})
    assert peri_scribe.fires.complexes.row_observation(row, read.paths[-1]) is None


def test_row_observation_requires_child_identifier() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history([(0, 1, 1)])
    row = dataclasses.replace(
        read.rows[-1],
        record=dataclasses.replace(read.rows[-1].record, identifiers=frozenset()),
    )
    assert peri_scribe.fires.complexes.row_observation(row, read.paths[-1]) is None


@pytest.mark.parametrize(
    "path",
    ["undated.gpkg", "1,lastEdit=9999999999999999999.gpkg"],
)
def test_snapshot_clock_tolerates_missing_or_out_of_range_time(path: str) -> None:
    time, _serial = peri_scribe.fires.complexes.snapshot_clock(pathlib.Path(path))
    assert time is None


def test_observations_requires_aligned_membership_provenance() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history([(0, 1, 1)])
    with pytest.raises(ValueError, match="matching lengths"):
        peri_scribe.fires.complexes.observations(
            read.rows,
            read.paths,
            read.memberships,
            (pathlib.Path("one.gpkg"), pathlib.Path("two.gpkg")),
        )


def test_observations_uses_snapshot_clock_without_an_incident_date() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history([(0, 1, 1)])
    path = pathlib.Path("WFIGS_Incident_Locations/000002,lastEdit=1000.gpkg")
    declarations = peri_scribe.fires.complexes.observations(
        (),
        (),
        (dataclasses.replace(read.memberships[0], observation_time=None),),
        (path,),
    )
    assert len(declarations) == 1
    assert declarations[0].incident_location
    assert declarations[0].order == (
        datetime.datetime(1970, 1, 1, 0, 0, 1, tzinfo=datetime.UTC),
        True,
        2,
    )


def test_observations_does_not_duplicate_renamed_membership() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history([(0, 1, 1)])
    membership = dataclasses.replace(read.memberships[0], complex_name="Other spelling")
    declarations = peri_scribe.fires.complexes.observations(
        read.rows,
        read.paths,
        (membership,),
        (read.paths[-1],),
    )
    assert len(declarations) == 1


@pytest.mark.parametrize(
    "time",
    [None, datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)],
    ids=["undated", "newer"],
)
def test_observations_preserves_distinct_incident_clocks_in_one_snapshot(
    time: datetime.datetime | None,
) -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history([(0, 1, 1)])
    membership = dataclasses.replace(read.memberships[0], observation_time=time)
    declarations = peri_scribe.fires.complexes.observations(
        read.rows,
        read.paths,
        (membership,),
        (read.paths[-1],),
    )
    assert [declaration.observation_time for declaration in declarations] == [
        datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        time,
    ]


def test_resolve_rejects_reusing_assigned_fire_objects() -> None:
    fire = peri_scribe.models.Fire(
        name="Child",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    peri_scribe.models.FireComplex(
        name="Parent",
        identifier="parent",
        fires=frozenset({fire}),
    )
    with pytest.raises(ValueError, match="unassigned fire objects"):
        peri_scribe.fires.complexes.resolve([], {"child": fire})


def test_resolve_exact_tie_leaves_ownership_unassigned() -> None:
    fire = peri_scribe.models.Fire(
        name="Child",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    declarations = [
        peri_scribe.fires.complexes.MembershipObservation(
            fire_identifier="child",
            complex_identifier=parent,
            complex_name=parent,
        )
        for parent in ("one", "two")
    ]
    complexes = peri_scribe.fires.complexes.resolve(declarations, {"child": fire})
    assert fire.complex is None
    assert all(not complex_.fires for complex_ in complexes)


def test_resolve_ignores_unknown_child() -> None:
    declaration = peri_scribe.fires.complexes.MembershipObservation(
        fire_identifier="unknown",
        complex_identifier="parent",
        complex_name="Parent",
    )
    assert peri_scribe.fires.complexes.resolve([declaration], {}) == []
