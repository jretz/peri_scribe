"""Tests for peri_scribe.fires.sources."""

from __future__ import annotations

import pathlib
import re

import pytest
import shapely.geometry
import structlog

import peri_scribe.exceptions
import peri_scribe.execution
import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.sources.snapshots
import tests.helpers.doubles.peri_scribe.fires.sources
import tests.helpers.factories.peri_scribe.fires.sources
import tests.helpers.factories.peri_scribe.models


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


def test_prepare_fire_sources_shares_evidence_and_fire_identities_within_execution(
    repeated_geometry_sources: pathlib.Path,
) -> None:
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.sources.prepare_fire_sources(
            repeated_geometry_sources,
        )
        second = peri_scribe.fires.sources.prepare_fire_sources(
            repeated_geometry_sources / ".",
        )

    assert second is first


def test_prepare_fire_sources_keeps_distinct_directories_separate(
    repeated_geometry_sources: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.sources.prepare_fire_sources(
            repeated_geometry_sources,
        )
        second = peri_scribe.fires.sources.prepare_fire_sources(tmp_path / "empty")

    assert first.read.rows
    assert second.read.rows == ()


def test_prepare_fire_sources_reads_changed_evidence_in_each_execution(
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
    tmp_path: pathlib.Path,
) -> None:
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.sources.prepare_fire_sources(tmp_path / "sources")
    history_inputs[0] = peri_scribe.fires.sources.ReadFireSources(
        rows=(),
        paths=(),
        memberships=(),
    )
    with peri_scribe.execution.sharing():
        second = peri_scribe.fires.sources.prepare_fire_sources(tmp_path / "sources")

    assert first.read.rows
    assert second.read.rows == ()


def test_prepare_fire_sources_reconstructs_standalone_inputs(
    repeated_geometry_sources: pathlib.Path,
) -> None:
    first = peri_scribe.fires.sources.prepare_fire_sources(repeated_geometry_sources)
    second = peri_scribe.fires.sources.prepare_fire_sources(repeated_geometry_sources)

    assert second is not first
    assert second.read == first.read


def test_fire_sources_from_groups_keeps_distant_unnamed_identifiers_separate(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "CANYON",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=shapely.geometry.Point(0, 0),
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Canyon",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=shapely.geometry.Point(10, 10),
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert [fire.name for fire in fires] == ["CANYON", "Canyon"]


def test_fire_sources_from_groups_does_not_merge_same_named_fires_across_regions(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    # The CA "RIVER" perimeter and a distant WFIGS "River" location are distinct fires.
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "RIVER",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=shapely.geometry.Point(0, 0),
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "River",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
                geometry=shapely.geometry.Point(10, 10),
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert [fire.name for fire in fires] == ["RIVER", "River"]


def test_fire_sources_from_groups_links_member_fires_to_their_complex(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    fires = (
        tests.helpers.factories.peri_scribe.fires.sources
    ).complex_parent_and_child_fires(
        stub_fire_reader,
    )
    fire = fires[0]
    assert fire.complex is not None
    assert fire.complex.name == "ROWE CREEK COMPLEX"
    assert (
        fire.complex.identifier
        == tests.helpers.factories.peri_scribe.fires.sources.ROWE_CREEK_COMPLEX_ID
    )
    assert fire.complex.fires == frozenset({fire})
    assert next(iter(fire.complex.fires)).complex is fire.complex


def test_fire_sources_from_groups_propagates_unknown_layer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    fake_read_geopackage = (
        tests.helpers.doubles.peri_scribe.fires.sources.raise_unknown_layer
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
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        tests.helpers.factories.peri_scribe.fires.sources.listed_fires()


def test_fire_sources_from_groups_raises_system_exit_for_unreadable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    fake_read_geopackage = (
        tests.helpers.doubles.peri_scribe.fires.sources.raise_missing_snapshot
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
        tests.helpers.factories.peri_scribe.fires.sources.listed_fires()


def test_fire_sources_from_groups_prefers_most_common_mixed_case_spelling(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "PARK FIRE",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "PARK FIRE",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "PARK FIRE",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Park Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Park Fire",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
    ]


def test_fire_sources_from_groups_uses_most_common_spelling_when_none_is_mixed_case(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "PARK FIRE",
                tests.helpers.factories.peri_scribe.models.INACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "park fire",
                tests.helpers.factories.peri_scribe.models.INACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "park fire",
                tests.helpers.factories.peri_scribe.models.INACTIVE,
                geometry=location,
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="park fire",
            status=tests.helpers.factories.peri_scribe.models.INACTIVE,
        ),
    ]


def test_fire_sources_from_groups_breaks_mixed_case_ties_by_first_spelling(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Park Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "PARK Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Park Fire",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
    ]


def test_fire_sources_from_groups_marks_fire_active_when_any_record_is_active(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "ALTA",
                tests.helpers.factories.peri_scribe.models.INACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Alta",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Alta",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
    ]


def test_fire_sources_from_groups_merges_names_across_files(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Park Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "ALTA",
                tests.helpers.factories.peri_scribe.models.INACTIVE,
                geometry=shapely.geometry.Point(1, 1),
            ),
        ],
        pathlib.Path("two.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Park Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Creek Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=shapely.geometry.Point(2, 2),
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Park Fire",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
        peri_scribe.models.Fire(
            name="ALTA",
            status=tests.helpers.factories.peri_scribe.models.INACTIVE,
        ),
        peri_scribe.models.Fire(
            name="Creek Fire",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
    ]


def test_fire_sources_from_groups_merges_identifier_aliases(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "0445 CROSSWHITE",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                identifiers={
                    tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
                },
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Crosswhite",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                identifiers={
                    tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
                },
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
            aliases=frozenset({
                tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
            }),
        ),
    ]


def test_fire_sources_from_groups_keeps_distinct_identifiers_separate(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    # The same name in different regions is a different fire, even when both are
    # identified, so the spatial gate keeps them apart.
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "CANYON",
                tests.helpers.factories.peri_scribe.models.INACTIVE,
                identifiers={"2026-cacdd-007101"},
                geometry=shapely.geometry.Point(0, 0),
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Canyon",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                identifiers={"1dc015ad-5690-48c4-b8f3-fe02445b2369"},
                geometry=shapely.geometry.Point(10, 10),
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="CANYON",
            status=tests.helpers.factories.peri_scribe.models.INACTIVE,
            identifier="2026-cacdd-007101",
            aliases=frozenset({"2026-cacdd-007101"}),
        ),
        peri_scribe.models.Fire(
            name="Canyon",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier="1dc015ad-5690-48c4-b8f3-fe02445b2369",
            aliases=frozenset({"1dc015ad-5690-48c4-b8f3-fe02445b2369"}),
        ),
    ]


def test_fire_sources_from_groups_merges_ufi_and_guid_through_a_shared_record(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    # The CA layer's FIRIS records carry the unique fire identifier; the WFIGS records
    # carry both the GUID and the unique fire identifier, linking them all.
    location = shapely.geometry.Point(0, 0)
    unique_id = "2026-nvccd-030683"
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "BUG",
                tests.helpers.factories.peri_scribe.models.INACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Bug",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                identifiers={unique_id},
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Bug",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                identifiers={unique_id, guid},
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Bug",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=unique_id,
            aliases=frozenset({unique_id, guid}),
        ),
    ]


def test_fire_sources_from_groups_merges_unidentified_name_matches(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    location = shapely.geometry.Point(0, 0)
    unique_id = "2026-nvccd-030683"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "BUG",
                tests.helpers.factories.peri_scribe.models.INACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Bug",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                identifiers={unique_id},
                geometry=location,
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Bug",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=unique_id,
            aliases=frozenset({unique_id}),
        ),
    ]


def test_fire_sources_from_groups_merges_same_named_fires_at_the_same_location(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    # Two records of the same fire can carry different identifiers, for example a
    # re-mapping that received a new GUID. At the same location they are one fire.
    location = shapely.geometry.Point(0, 0)
    may_guid = "a4eb258a-f5d1-46c3-9560-8fbc8042d9c3"
    june_guid = "1ce6519c-30a2-4615-a8a2-a25fbff2faa2"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "SANDY",
                tests.helpers.factories.peri_scribe.models.INACTIVE,
                identifiers={may_guid},
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "SANDY",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                identifiers={june_guid},
                geometry=location,
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="SANDY",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=june_guid,
            aliases=frozenset({may_guid, june_guid}),
        ),
    ]


def test_fire_sources_from_groups_merges_mission_name_variants(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    # "RUMSEY" and the unidentified "RUMSEY-UPDATED" record share the base name from the
    # mission code, so they are one fire.
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "RUMSEY",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                identifiers={"5f1293e8-bc81-4265-83ed-d06ee6361bd6"},
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "RUMSEY-UPDATED",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                names=frozenset({"rumsey updated", "rumsey"}),
                geometry=location,
            ),
        ],
    })
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="RUMSEY",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier="5f1293e8-bc81-4265-83ed-d06ee6361bd6",
            aliases=frozenset({"5f1293e8-bc81-4265-83ed-d06ee6361bd6"}),
        ),
    ]


def test_fire_sources_from_groups_excludes_complex_parents(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    fires = (
        tests.helpers.factories.peri_scribe.fires.sources
    ).complex_parent_and_child_fires(
        stub_fire_reader,
    )
    assert fires == [
        peri_scribe.models.Fire(
            name="0445 CROSSWHITE",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
            aliases=frozenset({
                tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
            }),
        ),
    ]


def test_fire_sources_from_groups_combines_complex_memberships(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    membership = peri_scribe.models.ComplexMembership(
        fire_identifier=tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
        complex_identifier=(
            tests.helpers.factories.peri_scribe.fires.sources.ROWE_CREEK_COMPLEX_ID
        ),
        complex_name="ROWE CREEK COMPLEX",
    )
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                tests.helpers.factories.peri_scribe.models.fire_record(
                    "0445 CROSSWHITE",
                    tests.helpers.factories.peri_scribe.models.ACTIVE,
                    identifiers={
                        tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
                    },
                ),
            ],
            pathlib.Path("two.gpkg"): [
                tests.helpers.factories.peri_scribe.models.fire_record(
                    "Crosswhite",
                    tests.helpers.factories.peri_scribe.models.ACTIVE,
                    identifiers={
                        tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
                    },
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [membership],
            pathlib.Path("two.gpkg"): [membership],
        },
    )
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
            aliases=frozenset({
                tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
            }),
        ),
    ]
    assert fires[0].complex is not None
    assert len(fires[0].complex.fires) == 1


def test_fire_sources_from_groups_excludes_parent_group_with_multiple_identifiers(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    parent_guid = "b0b0e959-6d11-4831-951a-c464f0f3ab45"
    parent_ufi = "2026-cabdu-011375"
    child_id = "ef21ead9-ce4d-48f6-964f-46a398857263"
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                tests.helpers.factories.peri_scribe.models.fire_record(
                    "CINDER COMPLEX",
                    tests.helpers.factories.peri_scribe.models.INACTIVE,
                    geometry=location,
                ),
                tests.helpers.factories.peri_scribe.models.fire_record(
                    "CINDER COMPLEX",
                    tests.helpers.factories.peri_scribe.models.INACTIVE,
                    identifiers={parent_ufi},
                    geometry=location,
                ),
                tests.helpers.factories.peri_scribe.models.fire_record(
                    "CINDER COMPLEX",
                    tests.helpers.factories.peri_scribe.models.ACTIVE,
                    identifiers={parent_guid, parent_ufi},
                    geometry=location,
                ),
                tests.helpers.factories.peri_scribe.models.fire_record(
                    "5-3",
                    tests.helpers.factories.peri_scribe.models.ACTIVE,
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
    fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    assert fires == [
        peri_scribe.models.Fire(
            name="5-3",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=child_id,
            aliases=frozenset({child_id}),
        ),
    ]


def test_fire_sources_from_groups_skips_membership_for_unidentified_fire(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                tests.helpers.factories.peri_scribe.models.fire_record(
                    "Crosswhite",
                    tests.helpers.factories.peri_scribe.models.ACTIVE,
                    identifiers={
                        tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
                    },
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier="unknown-fire",
                    complex_identifier=(
                        tests.helpers.factories.peri_scribe.fires.sources.ROWE_CREEK_COMPLEX_ID
                    ),
                    complex_name="ROWE CREEK COMPLEX",
                ),
                peri_scribe.models.ComplexMembership(
                    fire_identifier=(
                        tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID
                    ),
                    complex_identifier=(
                        tests.helpers.factories.peri_scribe.fires.sources.ROWE_CREEK_COMPLEX_ID
                    ),
                    complex_name="ROWE CREEK COMPLEX",
                ),
            ],
        },
    )
    with structlog.testing.capture_logs() as captured:
        fires = tests.helpers.factories.peri_scribe.fires.sources.listed_fires()
    captured = [entry for entry in captured if entry["log_level"] == "warning"]
    assert captured[0]["event"] == "Complex membership references an unidentified fire"
    assert captured[0]["fire_identifier"] == "unknown-fire"
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
            aliases=frozenset({
                tests.helpers.factories.peri_scribe.fires.sources.CROSSWHITE_ID,
            }),
        ),
    ]
    assert fires[0].complex is not None
    assert fires[0].complex.fires == frozenset({fires[0]})


def test_fire_sources_from_groups_collects_paths_for_each_fire(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    one = pathlib.Path("one.gpkg")
    two = pathlib.Path("two.gpkg")
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        one: [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Park Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
        ],
        two: [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Park Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
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
                status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            ),
            paths=(one, two),
        ),
    ]


def test_fire_sources_from_groups_deduplicates_paths_for_a_fire(
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    path = pathlib.Path("one.gpkg")
    location = shapely.geometry.Point(0, 0)
    stub_fire_reader({
        path: [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Park Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
                geometry=location,
            ),
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Park Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
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
                status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            ),
            paths=(path,),
        ),
    ]
