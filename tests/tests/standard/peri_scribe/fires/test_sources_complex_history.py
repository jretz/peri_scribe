"""Current complex ownership follows incident history and parent mergers."""

import dataclasses

import peri_scribe.fires.sources
import tests.helpers.factories.peri_scribe.fires.complexes


def test_group_fire_sources_uses_latest_incident_membership() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history(
        [(0, 2, 2), (0, 1, 1)],
    )
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    child = groups.fires[0]
    assert child.complex is not None
    assert child.complex.identifier == "fire-2"


def test_group_fire_sources_follows_a_parent_complex_merger() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history(
        [(0, 1, 1), (1, 2, 2)],
    )
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    child = groups.fires[0]
    assert child.complex is not None
    assert child.complex.identifier == "fire-2"
    assert child in child.complex.fires
    assert all(member.complex is child.complex for member in child.complex.fires)
    visible = peri_scribe.fires.sources.fire_sources_from_groups(groups)
    assert [source.fire.identifier for source in visible] == ["fire-0"]


def test_group_fire_sources_honors_explicit_release() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history(
        [(0, 1, 1), (0, None, 2)],
    )
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    assert groups.fires[0].complex is None
    assert "fire-1" in groups.complex_identifiers


def test_group_fire_sources_rejects_merger_cycles() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history(
        [(0, 1, 1), (1, 2, 2), (2, 1, 3)],
    )
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    assert groups.fires[0].complex is None


def test_group_fire_sources_keeps_parent_when_later_relationship_is_missing() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history(
        [(0, 1, 1), (0, None, 2)],
    )
    row = dataclasses.replace(read.rows[-1], attributes={"attr_IsCpxChild": " "})
    read = dataclasses.replace(read, rows=(*read.rows[:-1], row))
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    assert groups.fires[0].complex is not None
    assert groups.fires[0].complex.identifier == "fire-1"


def test_group_fire_sources_transfers_parent_without_display_name() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history(
        [(0, 1, 1), (0, 2, 2)],
    )
    attributes = dict(read.rows[-1].attributes)
    attributes.pop("attr_CpxName")
    row = dataclasses.replace(read.rows[-1], attributes=attributes)
    read = dataclasses.replace(read, rows=(*read.rows[:-1], row))
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    assert groups.fires[0].complex is not None
    assert groups.fires[0].complex.identifier == "fire-2"


def test_group_fire_sources_prefers_location_at_same_incident_time() -> None:
    read = tests.helpers.factories.peri_scribe.fires.complexes.history(
        [(0, 2, 1), (0, 1, 1)],
    )
    location = dataclasses.replace(
        read.rows[-2],
        attributes={
            key.removeprefix("attr_"): value
            for key, value in read.rows[-2].attributes.items()
        },
    )
    read = dataclasses.replace(read, rows=(*read.rows[:-2], location, read.rows[-1]))
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    assert groups.fires[0].complex is not None
    assert groups.fires[0].complex.identifier == "fire-2"
