"""Tests for peri_scribe.fires.sources."""

from __future__ import annotations

import pathlib
import re

import hypothesis
import hypothesis.strategies
import pytest
import shapely.geometry
import structlog

import peri_scribe.exceptions
import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.sources.snapshots
import tests.factories
import tests.peri_scribe.fires.sources_helpers
import tests.peri_scribe.geo.database_helpers


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    snapshots=hypothesis.strategies.dictionaries(
        hypothesis.strategies.integers(0, 5),
        tests.peri_scribe.geo.database_helpers.snapshot_contents(),
        max_size=5,
    ),
)
def test_read_fire_sources_preserves_each_rows_provenance_and_all_memberships(
    snapshots: dict[int, peri_scribe.geo.package.GeopackageContents],
) -> None:
    contents = {
        pathlib.Path(f"sources/snapshot-{serial}.gpkg"): snapshot
        for serial, snapshot in snapshots.items()
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            peri_scribe.sources.snapshots,
            "geo_package_files",
            lambda _directory: list(contents),
        )
        patch.setattr(
            peri_scribe.fires.sources,
            "read_fire_geopackage",
            lambda path, **_kwargs: contents[path],
        )
        actual = peri_scribe.fires.sources.read_fire_sources(pathlib.Path("sources"))
    assert list(zip(actual.paths, actual.rows, strict=True)) == [
        (path, row) for path, snapshot in contents.items() for row in snapshot.rows
    ]
    assert actual.memberships == tuple(
        membership
        for snapshot in contents.values()
        for membership in snapshot.memberships
    )


def test_read_fire_sources_shares_snapshot_geometries(
    repeated_geometry_sources: pathlib.Path,
) -> None:
    read = peri_scribe.fires.sources.read_fire_sources(repeated_geometry_sources)
    assert read.rows[0].record.geometry is read.rows[1].record.geometry


def test_read_fire_sources_preserves_observations_with_shared_geometry(
    repeated_geometry_sources: pathlib.Path,
) -> None:
    read = peri_scribe.fires.sources.read_fire_sources(repeated_geometry_sources)
    assert [row.record.name for row in read.rows] == ["First", "Second"]
    assert [row.attributes["revision"] for row in read.rows] == [0, 1]
    assert read.paths == tuple(sorted(repeated_geometry_sources.rglob("*.gpkg")))


def test_read_fire_sources_scopes_geometry_sharing_to_each_read(
    repeated_geometry_sources: pathlib.Path,
) -> None:
    first = peri_scribe.fires.sources.read_fire_sources(repeated_geometry_sources)
    second = peri_scribe.fires.sources.read_fire_sources(repeated_geometry_sources)
    assert first.rows[0].record.geometry is not second.rows[0].record.geometry


def test_fire_sources_from_groups_keeps_distant_unnamed_identifiers_separate(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "CANYON",
                tests.factories.ACTIVE,
                geometry=shapely.geometry.Point(0, 0),
            ),
            tests.factories.fire_record(
                "Canyon",
                tests.factories.ACTIVE,
                geometry=shapely.geometry.Point(10, 10),
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert [fire.name for fire in fires] == ["CANYON", "Canyon"]


def test_fire_sources_from_groups_does_not_merge_same_named_fires_across_regions(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    # The CA "RIVER" perimeter and a distant WFIGS "River" location are distinct fires.
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "RIVER",
                tests.factories.ACTIVE,
                geometry=shapely.geometry.Point(0, 0),
            ),
            tests.factories.fire_record(
                "River",
                tests.factories.ACTIVE,
                identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
                geometry=shapely.geometry.Point(10, 10),
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert [fire.name for fire in fires] == ["RIVER", "River"]


def test_fire_sources_from_groups_links_member_fires_to_their_complex(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    fires = tests.peri_scribe.fires.sources_helpers.complex_parent_and_child_fires(
        stub_fire_reader,
    )
    fire = fires[0]
    assert fire.complex is not None
    assert fire.complex.name == "ROWE CREEK COMPLEX"
    assert (
        fire.complex.identifier
        == tests.peri_scribe.fires.sources_helpers.ROWE_CREEK_COMPLEX_ID
    )
    assert fire.complex.fires == frozenset({fire})
    assert next(iter(fire.complex.fires)).complex is fire.complex


def test_fire_sources_from_groups_propagates_unknown_layer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    fake_read_geopackage = tests.peri_scribe.fires.sources_helpers.raise_unknown_layer

    monkeypatch.setattr(
        peri_scribe.geo.package,
        "read_geopackage",
        fake_read_geopackage,
    )
    monkeypatch.setattr(
        peri_scribe.sources.snapshots,
        "geo_package_files",
        lambda _directory: [pathlib.Path("fires.gpkg")],
    )
    with pytest.raises(
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        tests.peri_scribe.fires.sources_helpers.listed_fires()


def test_fire_sources_from_groups_raises_system_exit_for_unreadable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    fake_read_geopackage = (
        tests.peri_scribe.fires.sources_helpers.raise_missing_snapshot
    )

    monkeypatch.setattr(
        peri_scribe.geo.package,
        "read_geopackage",
        fake_read_geopackage,
    )
    monkeypatch.setattr(
        peri_scribe.sources.snapshots,
        "geo_package_files",
        lambda _directory: [pathlib.Path("fires.gpkg")],
    )
    with pytest.raises(
        SystemExit,
        match=re.escape("Failed to read fires.gpkg: no such file"),
    ):
        tests.peri_scribe.fires.sources_helpers.listed_fires()


def test_fire_sources_from_groups_prefers_most_common_mixed_case_spelling(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "PARK FIRE",
                tests.factories.ACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "PARK FIRE",
                tests.factories.ACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "PARK FIRE",
                tests.factories.ACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "Park Fire",
                tests.factories.ACTIVE,
                geometry=location,
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(name="Park Fire", status=tests.factories.ACTIVE),
    ]


def test_fire_sources_from_groups_uses_most_common_spelling_when_none_is_mixed_case(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "PARK FIRE",
                tests.factories.INACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "park fire",
                tests.factories.INACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "park fire",
                tests.factories.INACTIVE,
                geometry=location,
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(name="park fire", status=tests.factories.INACTIVE),
    ]


def test_fire_sources_from_groups_breaks_mixed_case_ties_by_first_spelling(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "Park Fire",
                tests.factories.ACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "PARK Fire",
                tests.factories.ACTIVE,
                geometry=location,
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(name="Park Fire", status=tests.factories.ACTIVE),
    ]


def test_fire_sources_from_groups_marks_fire_active_when_any_record_is_active(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "ALTA",
                tests.factories.INACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "Alta",
                tests.factories.ACTIVE,
                geometry=location,
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(name="Alta", status=tests.factories.ACTIVE),
    ]


def test_fire_sources_from_groups_merges_names_across_files(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "Park Fire",
                tests.factories.ACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "ALTA",
                tests.factories.INACTIVE,
                geometry=shapely.geometry.Point(1, 1),
            ),
        ],
        pathlib.Path("two.gpkg"): [
            tests.factories.fire_record(
                "Park Fire",
                tests.factories.ACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "Creek Fire",
                tests.factories.ACTIVE,
                geometry=shapely.geometry.Point(2, 2),
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(name="Park Fire", status=tests.factories.ACTIVE),
        peri_scribe.models.Fire(name="ALTA", status=tests.factories.INACTIVE),
        peri_scribe.models.Fire(name="Creek Fire", status=tests.factories.ACTIVE),
    ]


def test_fire_sources_from_groups_merges_identifier_aliases(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "0445 CROSSWHITE",
                tests.factories.ACTIVE,
                identifiers={tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID},
            ),
            tests.factories.fire_record(
                "Crosswhite",
                tests.factories.ACTIVE,
                identifiers={tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID},
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=tests.factories.ACTIVE,
            identifier=tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID,
            aliases=frozenset({tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID}),
        ),
    ]


def test_fire_sources_from_groups_keeps_distinct_identifiers_separate(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    # The same name in different regions is a different fire, even when both are
    # identified, so the spatial gate keeps them apart.
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "CANYON",
                tests.factories.INACTIVE,
                identifiers={"2026-cacdd-007101"},
                geometry=shapely.geometry.Point(0, 0),
            ),
            tests.factories.fire_record(
                "Canyon",
                tests.factories.ACTIVE,
                identifiers={"1dc015ad-5690-48c4-b8f3-fe02445b2369"},
                geometry=shapely.geometry.Point(10, 10),
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="CANYON",
            status=tests.factories.INACTIVE,
            identifier="2026-cacdd-007101",
            aliases=frozenset({"2026-cacdd-007101"}),
        ),
        peri_scribe.models.Fire(
            name="Canyon",
            status=tests.factories.ACTIVE,
            identifier="1dc015ad-5690-48c4-b8f3-fe02445b2369",
            aliases=frozenset({"1dc015ad-5690-48c4-b8f3-fe02445b2369"}),
        ),
    ]


def test_fire_sources_from_groups_merges_ufi_and_guid_through_a_shared_record(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    # The CA layer's FIRIS records carry the unique fire identifier; the WFIGS records
    # carry both the GUID and the unique fire identifier, linking them all.
    location = shapely.geometry.Point(0, 0)
    unique_id = "2026-nvccd-030683"
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "BUG",
                tests.factories.INACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "Bug",
                tests.factories.ACTIVE,
                identifiers={unique_id},
                geometry=location,
            ),
            tests.factories.fire_record(
                "Bug",
                tests.factories.ACTIVE,
                identifiers={unique_id, guid},
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Bug",
            status=tests.factories.ACTIVE,
            identifier=unique_id,
            aliases=frozenset({unique_id, guid}),
        ),
    ]


def test_fire_sources_from_groups_merges_unidentified_name_matches(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    unique_id = "2026-nvccd-030683"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "BUG",
                tests.factories.INACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "Bug",
                tests.factories.ACTIVE,
                identifiers={unique_id},
                geometry=location,
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Bug",
            status=tests.factories.ACTIVE,
            identifier=unique_id,
            aliases=frozenset({unique_id}),
        ),
    ]


def test_fire_sources_from_groups_merges_same_named_fires_at_the_same_location(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    # Two records of the same fire can carry different identifiers, for example a
    # re-mapping that received a new GUID. At the same location they are one fire.
    location = shapely.geometry.Point(0, 0)
    may_guid = "a4eb258a-f5d1-46c3-9560-8fbc8042d9c3"
    june_guid = "1ce6519c-30a2-4615-a8a2-a25fbff2faa2"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "SANDY",
                tests.factories.INACTIVE,
                identifiers={may_guid},
                geometry=location,
            ),
            tests.factories.fire_record(
                "SANDY",
                tests.factories.ACTIVE,
                identifiers={june_guid},
                geometry=location,
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="SANDY",
            status=tests.factories.ACTIVE,
            identifier=june_guid,
            aliases=frozenset({may_guid, june_guid}),
        ),
    ]


def test_fire_sources_from_groups_merges_mission_name_variants(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    # "RUMSEY" and the unidentified "RUMSEY-UPDATED" record share the base name from the
    # mission code, so they are one fire.
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.factories.fire_record(
                "RUMSEY",
                tests.factories.ACTIVE,
                identifiers={"5f1293e8-bc81-4265-83ed-d06ee6361bd6"},
                geometry=location,
            ),
            tests.factories.fire_record(
                "RUMSEY-UPDATED",
                tests.factories.ACTIVE,
                names=frozenset({"rumsey updated", "rumsey"}),
                geometry=location,
            ),
        ],
    })
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="RUMSEY",
            status=tests.factories.ACTIVE,
            identifier="5f1293e8-bc81-4265-83ed-d06ee6361bd6",
            aliases=frozenset({"5f1293e8-bc81-4265-83ed-d06ee6361bd6"}),
        ),
    ]


def test_fire_sources_from_groups_excludes_complex_parents(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    fires = tests.peri_scribe.fires.sources_helpers.complex_parent_and_child_fires(
        stub_fire_reader,
    )
    assert fires == [
        peri_scribe.models.Fire(
            name="0445 CROSSWHITE",
            status=tests.factories.ACTIVE,
            identifier=tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID,
            aliases=frozenset({tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID}),
        ),
    ]


def test_fire_sources_from_groups_combines_complex_memberships(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    membership = peri_scribe.models.ComplexMembership(
        fire_identifier=tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID,
        complex_identifier=(
            tests.peri_scribe.fires.sources_helpers.ROWE_CREEK_COMPLEX_ID
        ),
        complex_name="ROWE CREEK COMPLEX",
    )
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                tests.factories.fire_record(
                    "0445 CROSSWHITE",
                    tests.factories.ACTIVE,
                    identifiers={tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID},
                ),
            ],
            pathlib.Path("two.gpkg"): [
                tests.factories.fire_record(
                    "Crosswhite",
                    tests.factories.ACTIVE,
                    identifiers={tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID},
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [membership],
            pathlib.Path("two.gpkg"): [membership],
        },
    )
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=tests.factories.ACTIVE,
            identifier=tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID,
            aliases=frozenset({tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID}),
        ),
    ]
    assert fires[0].complex is not None
    assert len(fires[0].complex.fires) == 1


def test_fire_sources_from_groups_excludes_parent_group_with_multiple_identifiers(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    parent_guid = "b0b0e959-6d11-4831-951a-c464f0f3ab45"
    parent_ufi = "2026-cabdu-011375"
    child_id = "ef21ead9-ce4d-48f6-964f-46a398857263"
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                tests.factories.fire_record(
                    "CINDER COMPLEX",
                    tests.factories.INACTIVE,
                    geometry=location,
                ),
                tests.factories.fire_record(
                    "CINDER COMPLEX",
                    tests.factories.INACTIVE,
                    identifiers={parent_ufi},
                    geometry=location,
                ),
                tests.factories.fire_record(
                    "CINDER COMPLEX",
                    tests.factories.ACTIVE,
                    identifiers={parent_guid, parent_ufi},
                    geometry=location,
                ),
                tests.factories.fire_record(
                    "5-3",
                    tests.factories.ACTIVE,
                    identifiers={child_id},
                ),
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
    fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="5-3",
            status=tests.factories.ACTIVE,
            identifier=child_id,
            aliases=frozenset({child_id}),
        ),
    ]


def test_fire_sources_from_groups_skips_membership_for_unidentified_fire(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                tests.factories.fire_record(
                    "Crosswhite",
                    tests.factories.ACTIVE,
                    identifiers={tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID},
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier="unknown-fire",
                    complex_identifier=(
                        tests.peri_scribe.fires.sources_helpers.ROWE_CREEK_COMPLEX_ID
                    ),
                    complex_name="ROWE CREEK COMPLEX",
                ),
                peri_scribe.models.ComplexMembership(
                    fire_identifier=(
                        tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID
                    ),
                    complex_identifier=(
                        tests.peri_scribe.fires.sources_helpers.ROWE_CREEK_COMPLEX_ID
                    ),
                    complex_name="ROWE CREEK COMPLEX",
                ),
            ],
        },
    )
    with structlog.testing.capture_logs() as captured:
        fires = tests.peri_scribe.fires.sources_helpers.listed_fires()
    assert captured[0]["event"] == "Complex membership references an unidentified fire"
    assert captured[0]["fire_identifier"] == "unknown-fire"
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=tests.factories.ACTIVE,
            identifier=tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID,
            aliases=frozenset({tests.peri_scribe.fires.sources_helpers.CROSSWHITE_ID}),
        ),
    ]
    assert fires[0].complex is not None
    assert fires[0].complex.fires == frozenset({fires[0]})


def test_fire_sources_from_groups_collects_paths_for_each_fire(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    one = pathlib.Path("one.gpkg")
    two = pathlib.Path("two.gpkg")
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        one: [
            tests.factories.fire_record(
                "Park Fire",
                tests.factories.ACTIVE,
                geometry=location,
            ),
        ],
        two: [
            tests.factories.fire_record(
                "Park Fire",
                tests.factories.ACTIVE,
                geometry=location,
            ),
        ],
    })
    record_groups = peri_scribe.fires.sources.fire_record_groups(
        pathlib.Path("sources"),
    )
    sources = peri_scribe.fires.sources.fire_sources_from_groups(record_groups)
    assert sources == [
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(
                name="Park Fire",
                status=tests.factories.ACTIVE,
            ),
            paths=(one, two),
        ),
    ]


def test_fire_sources_from_groups_deduplicates_paths_for_a_fire(
    stub_fire_reader: tests.factories.StubFireReader,
) -> None:
    path = pathlib.Path("one.gpkg")
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        path: [
            tests.factories.fire_record(
                "Park Fire",
                tests.factories.ACTIVE,
                geometry=location,
            ),
            tests.factories.fire_record(
                "Park Fire",
                tests.factories.ACTIVE,
                geometry=location,
            ),
        ],
    })
    record_groups = peri_scribe.fires.sources.fire_record_groups(
        pathlib.Path("sources"),
    )
    sources = peri_scribe.fires.sources.fire_sources_from_groups(record_groups)
    assert sources == [
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(
                name="Park Fire",
                status=tests.factories.ACTIVE,
            ),
            paths=(path,),
        ),
    ]
