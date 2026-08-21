"""Tests for peri_scribe.fire_sources."""

from __future__ import annotations

import pathlib
import re
import typing

import pytest
import shapely.geometry
import structlog

import peri_scribe.exceptions
import peri_scribe.fire_sources
import peri_scribe.geo_package
import peri_scribe.models
import peri_scribe.snapshots
from tests.factories import ACTIVE, INACTIVE, fire_record


if typing.TYPE_CHECKING:
    from tests.factories import StubFireReader


CROSSWHITE_ID = "1b0219ee-5298-4fef-9927-c2666d9d53fc"
ROWE_CREEK_COMPLEX_ID = "b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3"


def listed_fires(
    directory: pathlib.Path = pathlib.Path("sources"),
) -> list[peri_scribe.models.Fire]:
    """Return the fires indexed from the GeoPackage files under *directory*.

    Args:
        directory: The directory tree holding GeoPackage files with fire data.
            Defaults to the canonical ``sources`` directory.

    Returns:
        The fires, in the order first encountered.
    """
    return [source.fire for source in peri_scribe.fire_sources.fire_sources(directory)]


def complex_parent_and_child_fires(
    stub_fire_reader: StubFireReader,
) -> list[peri_scribe.models.Fire]:
    """Return fires indexed from the canonical parent/child GeoPackage.

    Args:
        stub_fire_reader: The fixture installing in-memory fire reads.

    Returns:
        The parent and child fires, with the child linked to its complex.
    """
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                fire_record(
                    "ROWE CREEK COMPLEX",
                    ACTIVE,
                    identifiers={ROWE_CREEK_COMPLEX_ID},
                ),
                fire_record("0445 CROSSWHITE", ACTIVE, identifiers={CROSSWHITE_ID}),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier=CROSSWHITE_ID,
                    complex_identifier=ROWE_CREEK_COMPLEX_ID,
                    complex_name="ROWE CREEK COMPLEX",
                ),
            ],
        },
    )
    return listed_fires()


def test_fire_sources_prefers_most_common_mixed_case_spelling(
    stub_fire_reader: StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("PARK FIRE", ACTIVE, geometry=location),
            fire_record("PARK FIRE", ACTIVE, geometry=location),
            fire_record("PARK FIRE", ACTIVE, geometry=location),
            fire_record("Park Fire", ACTIVE, geometry=location),
        ],
    })
    fires = listed_fires()
    assert fires == [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)]


def test_fire_sources_uses_most_common_spelling_when_none_is_mixed_case(
    stub_fire_reader: StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("PARK FIRE", INACTIVE, geometry=location),
            fire_record("park fire", INACTIVE, geometry=location),
            fire_record("park fire", INACTIVE, geometry=location),
        ],
    })
    fires = listed_fires()
    assert fires == [peri_scribe.models.Fire(name="park fire", status=INACTIVE)]


def test_fire_sources_breaks_mixed_case_ties_by_first_spelling(
    stub_fire_reader: StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("Park Fire", ACTIVE, geometry=location),
            fire_record("PARK Fire", ACTIVE, geometry=location),
        ],
    })
    fires = listed_fires()
    assert fires == [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)]


def test_fire_sources_marks_fire_active_when_any_record_is_active(
    stub_fire_reader: StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("ALTA", INACTIVE, geometry=location),
            fire_record("Alta", ACTIVE, geometry=location),
        ],
    })
    fires = listed_fires()
    assert fires == [peri_scribe.models.Fire(name="Alta", status=ACTIVE)]


def test_fire_sources_merges_names_across_files(
    stub_fire_reader: StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("Park Fire", ACTIVE, geometry=location),
            fire_record("ALTA", INACTIVE, geometry=shapely.geometry.Point(1, 1)),
        ],
        pathlib.Path("two.gpkg"): [
            fire_record("Park Fire", ACTIVE, geometry=location),
            fire_record("Creek Fire", ACTIVE, geometry=shapely.geometry.Point(2, 2)),
        ],
    })
    fires = listed_fires()
    assert fires == [
        peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
        peri_scribe.models.Fire(name="ALTA", status=INACTIVE),
        peri_scribe.models.Fire(name="Creek Fire", status=ACTIVE),
    ]


def test_fire_sources_merges_records_with_same_identifier_under_different_names(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("0445 CROSSWHITE", ACTIVE, identifiers={CROSSWHITE_ID}),
            fire_record("Crosswhite", ACTIVE, identifiers={CROSSWHITE_ID}),
        ],
    })
    fires = listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=ACTIVE,
            identifier=CROSSWHITE_ID,
            aliases=frozenset({CROSSWHITE_ID}),
        ),
    ]


def test_fire_sources_keeps_same_named_fires_with_different_identifiers_separate(
    stub_fire_reader: StubFireReader,
) -> None:
    # The same name in different regions is a different fire, even when both are
    # identified, so the spatial gate keeps them apart.
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record(
                "CANYON",
                INACTIVE,
                identifiers={"2026-cacdd-007101"},
                geometry=shapely.geometry.Point(0, 0),
            ),
            fire_record(
                "Canyon",
                ACTIVE,
                identifiers={"1dc015ad-5690-48c4-b8f3-fe02445b2369"},
                geometry=shapely.geometry.Point(10, 10),
            ),
        ],
    })
    fires = listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="CANYON",
            status=INACTIVE,
            identifier="2026-cacdd-007101",
            aliases=frozenset({"2026-cacdd-007101"}),
        ),
        peri_scribe.models.Fire(
            name="Canyon",
            status=ACTIVE,
            identifier="1dc015ad-5690-48c4-b8f3-fe02445b2369",
            aliases=frozenset({"1dc015ad-5690-48c4-b8f3-fe02445b2369"}),
        ),
    ]


def test_fire_sources_merges_ufi_and_guid_through_a_shared_record(
    stub_fire_reader: StubFireReader,
) -> None:
    # The CA layer's FIRIS records carry the unique fire identifier; the WFIGS records
    # carry both the GUID and the unique fire identifier, linking them all.
    location = shapely.geometry.Point(0, 0)
    unique_id = "2026-nvccd-030683"
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("BUG", INACTIVE, geometry=location),
            fire_record("Bug", ACTIVE, identifiers={unique_id}, geometry=location),
            fire_record("Bug", ACTIVE, identifiers={unique_id, guid}),
        ],
    })
    fires = listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Bug",
            status=ACTIVE,
            identifier=unique_id,
            aliases=frozenset({unique_id, guid}),
        ),
    ]


def test_fire_sources_merges_unidentified_records_with_same_named_identified_records(
    stub_fire_reader: StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    unique_id = "2026-nvccd-030683"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("BUG", INACTIVE, geometry=location),
            fire_record("Bug", ACTIVE, identifiers={unique_id}, geometry=location),
        ],
    })
    fires = listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Bug",
            status=ACTIVE,
            identifier=unique_id,
            aliases=frozenset({unique_id}),
        ),
    ]


def test_fire_sources_keeps_same_named_unidentified_records_separate_when_far_apart(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("CANYON", ACTIVE, geometry=shapely.geometry.Point(0, 0)),
            fire_record("Canyon", ACTIVE, geometry=shapely.geometry.Point(10, 10)),
        ],
    })
    fires = listed_fires()
    assert [fire.name for fire in fires] == ["CANYON", "Canyon"]


def test_fire_sources_does_not_merge_same_named_fires_across_regions(
    stub_fire_reader: StubFireReader,
) -> None:
    # The CA "RIVER" perimeter and a distant WFIGS "River" location are distinct fires.
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("RIVER", ACTIVE, geometry=shapely.geometry.Point(0, 0)),
            fire_record(
                "River",
                ACTIVE,
                identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
                geometry=shapely.geometry.Point(10, 10),
            ),
        ],
    })
    fires = listed_fires()
    assert [fire.name for fire in fires] == ["RIVER", "River"]


def test_fire_sources_merges_same_named_fires_at_the_same_location(
    stub_fire_reader: StubFireReader,
) -> None:
    # Two records of the same fire can carry different identifiers, for example a
    # re-mapping that received a new GUID. At the same location they are one fire.
    location = shapely.geometry.Point(0, 0)
    may_guid = "a4eb258a-f5d1-46c3-9560-8fbc8042d9c3"
    june_guid = "1ce6519c-30a2-4615-a8a2-a25fbff2faa2"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record("SANDY", INACTIVE, identifiers={may_guid}, geometry=location),
            fire_record("SANDY", ACTIVE, identifiers={june_guid}, geometry=location),
        ],
    })
    fires = listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="SANDY",
            status=ACTIVE,
            identifier=june_guid,
            aliases=frozenset({may_guid, june_guid}),
        ),
    ]


def test_fire_sources_merges_mission_name_variants(
    stub_fire_reader: StubFireReader,
) -> None:
    # "RUMSEY" and the unidentified "RUMSEY-UPDATED" record share the base name from
    # the mission code, so they are one fire.
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            fire_record(
                "RUMSEY",
                ACTIVE,
                identifiers={"5f1293e8-bc81-4265-83ed-d06ee6361bd6"},
                geometry=location,
            ),
            fire_record(
                "RUMSEY-UPDATED",
                ACTIVE,
                names=frozenset({"rumsey updated", "rumsey"}),
                geometry=location,
            ),
        ],
    })
    fires = listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="RUMSEY",
            status=ACTIVE,
            identifier="5f1293e8-bc81-4265-83ed-d06ee6361bd6",
            aliases=frozenset({"5f1293e8-bc81-4265-83ed-d06ee6361bd6"}),
        ),
    ]


def test_fire_sources_excludes_complex_parents(
    stub_fire_reader: StubFireReader,
) -> None:
    fires = complex_parent_and_child_fires(stub_fire_reader)
    assert fires == [
        peri_scribe.models.Fire(
            name="0445 CROSSWHITE",
            status=ACTIVE,
            identifier=CROSSWHITE_ID,
            aliases=frozenset({CROSSWHITE_ID}),
        ),
    ]


def test_fire_sources_links_member_fires_to_their_complex(
    stub_fire_reader: StubFireReader,
) -> None:
    fires = complex_parent_and_child_fires(stub_fire_reader)
    fire = fires[0]
    assert fire.complex is not None
    assert fire.complex.name == "ROWE CREEK COMPLEX"
    assert fire.complex.identifier == ROWE_CREEK_COMPLEX_ID
    assert fire.complex.fires == frozenset({fire})
    assert next(iter(fire.complex.fires)).complex is fire.complex


def test_fire_sources_builds_one_complex_from_memberships_across_files(
    stub_fire_reader: StubFireReader,
) -> None:
    membership = peri_scribe.models.ComplexMembership(
        fire_identifier=CROSSWHITE_ID,
        complex_identifier=ROWE_CREEK_COMPLEX_ID,
        complex_name="ROWE CREEK COMPLEX",
    )
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                fire_record("0445 CROSSWHITE", ACTIVE, identifiers={CROSSWHITE_ID}),
            ],
            pathlib.Path("two.gpkg"): [
                fire_record("Crosswhite", ACTIVE, identifiers={CROSSWHITE_ID}),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [membership],
            pathlib.Path("two.gpkg"): [membership],
        },
    )
    fires = listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=ACTIVE,
            identifier=CROSSWHITE_ID,
            aliases=frozenset({CROSSWHITE_ID}),
        ),
    ]
    assert fires[0].complex is not None
    assert len(fires[0].complex.fires) == 1


def test_fire_sources_excludes_parent_group_with_multiple_identifiers(
    stub_fire_reader: StubFireReader,
) -> None:
    parent_guid = "b0b0e959-6d11-4831-951a-c464f0f3ab45"
    parent_ufi = "2026-cabdu-011375"
    child_id = "ef21ead9-ce4d-48f6-964f-46a398857263"
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                fire_record("CINDER COMPLEX", INACTIVE, geometry=location),
                fire_record(
                    "CINDER COMPLEX",
                    INACTIVE,
                    identifiers={parent_ufi},
                    geometry=location,
                ),
                fire_record(
                    "CINDER COMPLEX",
                    ACTIVE,
                    identifiers={parent_guid, parent_ufi},
                    geometry=location,
                ),
                fire_record("5-3", ACTIVE, identifiers={child_id}),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier=child_id,
                    complex_identifier=parent_guid,
                    complex_name="CINDER COMPLEX",
                ),
            ],
        },
    )
    fires = listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="5-3",
            status=ACTIVE,
            identifier=child_id,
            aliases=frozenset({child_id}),
        ),
    ]


def test_fire_complexes_skips_membership_for_unidentified_fire(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                fire_record("Crosswhite", ACTIVE, identifiers={CROSSWHITE_ID}),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier="unknown-fire",
                    complex_identifier=ROWE_CREEK_COMPLEX_ID,
                    complex_name="ROWE CREEK COMPLEX",
                ),
                peri_scribe.models.ComplexMembership(
                    fire_identifier=CROSSWHITE_ID,
                    complex_identifier=ROWE_CREEK_COMPLEX_ID,
                    complex_name="ROWE CREEK COMPLEX",
                ),
            ],
        },
    )
    with structlog.testing.capture_logs() as captured:
        fires = listed_fires()
    assert captured[0]["event"] == (
        "Complex membership references an unidentified fire"
    )
    assert captured[0]["fire_identifier"] == "unknown-fire"
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=ACTIVE,
            identifier=CROSSWHITE_ID,
            aliases=frozenset({CROSSWHITE_ID}),
        ),
    ]
    assert fires[0].complex is not None
    assert fires[0].complex.fires == frozenset({fires[0]})


def test_fire_sources_propagates_unknown_layer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_geopackage(_path: pathlib.Path) -> typing.Never:
        layer_name = "Mystery_Layer_0"
        raise peri_scribe.exceptions.UnknownLayerError(
            layer_name,
            pathlib.Path("fires.gpkg"),
        )

    monkeypatch.setattr(
        peri_scribe.geo_package,
        "read_geopackage",
        fake_read_geopackage,
    )
    monkeypatch.setattr(
        peri_scribe.snapshots,
        "geo_package_files",
        lambda _directory: [pathlib.Path("fires.gpkg")],
    )
    with pytest.raises(
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        listed_fires()


def test_fire_sources_raises_system_exit_for_unreadable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_geopackage(_path: pathlib.Path) -> typing.Never:
        message = "no such file"
        raise FileNotFoundError(message)

    monkeypatch.setattr(
        peri_scribe.geo_package,
        "read_geopackage",
        fake_read_geopackage,
    )
    monkeypatch.setattr(
        peri_scribe.snapshots,
        "geo_package_files",
        lambda _directory: [pathlib.Path("fires.gpkg")],
    )
    with pytest.raises(
        SystemExit,
        match=re.escape("Failed to read fires.gpkg: no such file"),
    ):
        listed_fires()


def test_fire_sources_collects_paths_for_each_fire(
    stub_fire_reader: StubFireReader,
) -> None:
    one = pathlib.Path("one.gpkg")
    two = pathlib.Path("two.gpkg")
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        one: [fire_record("Park Fire", ACTIVE, geometry=location)],
        two: [fire_record("Park Fire", ACTIVE, geometry=location)],
    })
    sources = peri_scribe.fire_sources.fire_sources(pathlib.Path("sources"))
    assert sources == [
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
            paths=(one, two),
        ),
    ]


def test_fire_sources_deduplicates_paths_for_a_fire(
    stub_fire_reader: StubFireReader,
) -> None:
    path = pathlib.Path("one.gpkg")
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        path: [
            fire_record("Park Fire", ACTIVE, geometry=location),
            fire_record("Park Fire", ACTIVE, geometry=location),
        ],
    })
    sources = peri_scribe.fire_sources.fire_sources(pathlib.Path("sources"))
    assert sources == [
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
            paths=(path,),
        ),
    ]
