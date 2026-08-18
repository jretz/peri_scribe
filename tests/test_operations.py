"""Tests for peri_scribe.operations."""

import datetime
import json
import pathlib
import re
import typing

import geopandas
import pandas as pd
import pydantic
import pyproj
import pytest
import shapely.geometry
import structlog

import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.operations
import peri_scribe.output


ACTIVE = peri_scribe.models.FireStatus.ACTIVE
INACTIVE = peri_scribe.models.FireStatus.INACTIVE


class StubFireReader(typing.Protocol):
    """A function that installs in-memory fire and membership stand-ins."""

    def __call__(
        self,
        fires_by_path: dict[pathlib.Path, list[peri_scribe.models.Fire]],
        memberships_by_path: dict[
            pathlib.Path,
            list[peri_scribe.models.ComplexMembership],
        ]
        | None = None,
    ) -> None: ...


@pytest.fixture
def stub_fire_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> StubFireReader:
    """Point the GeoPackage readers at in-memory fires and memberships.

    Returns:
        A function that installs stand-ins serving the given fires and
        memberships per GeoPackage path.
    """

    def stub(
        fires_by_path: dict[pathlib.Path, list[peri_scribe.models.Fire]],
        memberships_by_path: dict[
            pathlib.Path,
            list[peri_scribe.models.ComplexMembership],
        ]
        | None = None,
    ) -> None:
        def fake_fire_names(
            path: pathlib.Path,
        ) -> typing.Iterator[peri_scribe.models.Fire]:
            yield from fires_by_path.get(path, [])

        def fake_complex_memberships(
            path: pathlib.Path,
        ) -> typing.Iterator[peri_scribe.models.ComplexMembership]:
            yield from (memberships_by_path or {}).get(path, [])

        def fake_geo_package_files(
            _directory: pathlib.Path,
        ) -> list[pathlib.Path]:
            return sorted(set(fires_by_path) | set(memberships_by_path or {}))

        monkeypatch.setattr(
            peri_scribe.geo_data,
            "fire_names",
            fake_fire_names,
        )
        monkeypatch.setattr(
            peri_scribe.geo_data,
            "complex_memberships",
            fake_complex_memberships,
        )
        monkeypatch.setattr(
            peri_scribe.operations,
            "geo_package_files",
            fake_geo_package_files,
        )

    return stub


def listed_fires(directory: pathlib.Path) -> list[peri_scribe.models.Fire]:
    """Return the fires indexed from the GeoPackage files under *directory*.

    Args:
        directory: The directory tree holding GeoPackage files with fire data.

    Returns:
        The fires, in the order first encountered.
    """
    return [
        source.fire
        for source in peri_scribe.operations.fire_sources(directory)
    ]


def test_fire_sources_prefers_most_common_mixed_case_spelling(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="PARK FIRE", status=ACTIVE),
            peri_scribe.models.Fire(name="PARK FIRE", status=ACTIVE),
            peri_scribe.models.Fire(name="PARK FIRE", status=ACTIVE),
            peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)]


def test_fire_sources_uses_most_common_spelling_when_none_is_mixed_case(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="PARK FIRE", status=INACTIVE),
            peri_scribe.models.Fire(name="park fire", status=INACTIVE),
            peri_scribe.models.Fire(name="park fire", status=INACTIVE),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [peri_scribe.models.Fire(name="park fire", status=INACTIVE)]


def test_fire_sources_breaks_mixed_case_ties_by_first_spelling(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
            peri_scribe.models.Fire(name="PARK Fire", status=ACTIVE),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)]


def test_fire_sources_marks_fire_active_when_any_record_is_active(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="ALTA", status=INACTIVE),
            peri_scribe.models.Fire(name="Alta", status=ACTIVE),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [peri_scribe.models.Fire(name="Alta", status=ACTIVE)]


def test_fire_sources_merges_names_across_files(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
            peri_scribe.models.Fire(name="ALTA", status=INACTIVE),
        ],
        pathlib.Path("two.gpkg"): [
            peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
            peri_scribe.models.Fire(name="Creek Fire", status=ACTIVE),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [
        peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
        peri_scribe.models.Fire(name="ALTA", status=INACTIVE),
        peri_scribe.models.Fire(name="Creek Fire", status=ACTIVE),
    ]


def test_fire_sources_merges_records_with_same_identifier_under_different_names(
    stub_fire_reader: StubFireReader,
) -> None:
    crosswhite_id = "1b0219ee-5298-4fef-9927-c2666d9d53fc"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(
                name="0445 CROSSWHITE",
                status=ACTIVE,
                identifier=crosswhite_id,
            ),
            peri_scribe.models.Fire(
                name="Crosswhite",
                status=ACTIVE,
                identifier=crosswhite_id,
            ),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=ACTIVE,
            identifier=crosswhite_id,
        ),
    ]


def test_fire_sources_keeps_same_named_fires_with_different_identifiers_separate(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(
                name="CANYON",
                status=INACTIVE,
                identifier="2026-cacdd-007101",
            ),
            peri_scribe.models.Fire(
                name="Canyon",
                status=ACTIVE,
                identifier="1dc015ad-5690-48c4-b8f3-fe02445b2369",
            ),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [
        peri_scribe.models.Fire(
            name="CANYON",
            status=INACTIVE,
            identifier="2026-cacdd-007101",
        ),
        peri_scribe.models.Fire(
            name="Canyon",
            status=ACTIVE,
            identifier="1dc015ad-5690-48c4-b8f3-fe02445b2369",
        ),
    ]


def test_fire_sources_merges_unidentified_records_with_same_named_identified_records(
    stub_fire_reader: StubFireReader,
) -> None:
    # The CA layer's FIRIS records carry no identifier; the WFIGS records for the
    # same fire do. All of them are the same fire (Bug).
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="BUG", status=INACTIVE),
            peri_scribe.models.Fire(
                name="Bug",
                status=ACTIVE,
                identifier="2026-nvccd-030683",
            ),
            peri_scribe.models.Fire(
                name="Bug",
                status=ACTIVE,
                identifier="286b7f1d-8945-4a5d-9d81-5235c18af1fe",
            ),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [
        peri_scribe.models.Fire(
            name="Bug",
            status=ACTIVE,
            identifier="2026-nvccd-030683",
        ),
    ]


def test_fire_sources_merges_keyed_record_with_later_unidentified_same_named_record(
    stub_fire_reader: StubFireReader,
) -> None:
    bug_id = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="Bug", status=ACTIVE, identifier=bug_id),
            peri_scribe.models.Fire(name="BUG", status=INACTIVE),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [
        peri_scribe.models.Fire(name="Bug", status=ACTIVE, identifier=bug_id),
    ]


def test_fire_sources_merges_identified_records_through_a_shared_unidentified_record(
    stub_fire_reader: StubFireReader,
) -> None:
    # Two records with different identifiers and an unidentified record of the
    # same name are all one fire, since the unidentified record connects them.
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(
                name="Bug",
                status=ACTIVE,
                identifier="286b7f1d-8945-4a5d-9d81-5235c18af1fe",
            ),
            peri_scribe.models.Fire(name="BUG", status=INACTIVE),
            peri_scribe.models.Fire(
                name="Bug",
                status=ACTIVE,
                identifier="2026-nvccd-030683",
            ),
        ],
    })
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [
        peri_scribe.models.Fire(
            name="Bug",
            status=ACTIVE,
            identifier="286b7f1d-8945-4a5d-9d81-5235c18af1fe",
        ),
    ]


def test_group_fire_records_preserves_first_encountered_order() -> None:
    records = [
        peri_scribe.models.Fire(name="A", status=ACTIVE, identifier="id-a"),
        peri_scribe.models.Fire(name="B", status=ACTIVE, identifier="id-b"),
        peri_scribe.models.Fire(name="A", status=ACTIVE, identifier="id-a"),
    ]
    groups = peri_scribe.operations.group_fire_records(records)
    assert [group[0].name for group in groups] == ["A", "B"]


def test_group_fire_records_merges_names_differing_only_in_whitespace() -> None:
    records = [
        peri_scribe.models.Fire(name="PARK FIRE", status=ACTIVE),
        peri_scribe.models.Fire(name="  park   fire ", status=INACTIVE),
    ]
    groups = peri_scribe.operations.group_fire_records(records)
    assert groups == [records]


def test_normalize_fire_name() -> None:
    assert peri_scribe.operations.normalize_fire_name("  Park   FIRE ") == "park fire"


def test_most_common_fire_uses_first_identifier() -> None:
    bug_id = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    occurrences = [
        peri_scribe.models.Fire(name="Bug", status=ACTIVE),
        peri_scribe.models.Fire(name="Bug", status=ACTIVE, identifier=bug_id),
        peri_scribe.models.Fire(
            name="Bug",
            status=ACTIVE,
            identifier="2026-nvccd-030683",
        ),
    ]
    assert peri_scribe.operations.most_common_fire(occurrences) == (
        peri_scribe.models.Fire(name="Bug", status=ACTIVE, identifier=bug_id)
    )


def test_is_mixed_case() -> None:
    assert peri_scribe.operations.is_mixed_case("Park Fire")
    assert not peri_scribe.operations.is_mixed_case("PARK FIRE")
    assert not peri_scribe.operations.is_mixed_case("park fire")
    assert not peri_scribe.operations.is_mixed_case("3-1")


def test_fire_sources_excludes_complex_parents(
    stub_fire_reader: StubFireReader,
) -> None:
    parent_id = "b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3"
    child_id = "1b0219ee-5298-4fef-9927-c2666d9d53fc"
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.Fire(
                    name="ROWE CREEK COMPLEX",
                    status=ACTIVE,
                    identifier=parent_id,
                ),
                peri_scribe.models.Fire(
                    name="0445 CROSSWHITE",
                    status=ACTIVE,
                    identifier=child_id,
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier=child_id,
                    complex_identifier=parent_id,
                    complex_name="ROWE CREEK COMPLEX",
                ),
            ],
        },
    )
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [
        peri_scribe.models.Fire(
            name="0445 CROSSWHITE",
            status=ACTIVE,
            identifier=child_id,
        ),
    ]


def test_fire_sources_links_member_fires_to_their_complex(
    stub_fire_reader: StubFireReader,
) -> None:
    parent_id = "b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3"
    child_id = "1b0219ee-5298-4fef-9927-c2666d9d53fc"
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.Fire(
                    name="ROWE CREEK COMPLEX",
                    status=ACTIVE,
                    identifier=parent_id,
                ),
                peri_scribe.models.Fire(
                    name="0445 CROSSWHITE",
                    status=ACTIVE,
                    identifier=child_id,
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier=child_id,
                    complex_identifier=parent_id,
                    complex_name="ROWE CREEK COMPLEX",
                ),
            ],
        },
    )
    fires = listed_fires(pathlib.Path("sources"))
    fire = fires[0]
    assert fire.complex is not None
    assert fire.complex.name == "ROWE CREEK COMPLEX"
    assert fire.complex.identifier == parent_id
    assert fire.complex.fires == frozenset({fire})
    assert next(iter(fire.complex.fires)).complex is fire.complex


def test_fire_sources_builds_one_complex_from_memberships_across_files(
    stub_fire_reader: StubFireReader,
) -> None:
    parent_id = "b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3"
    child_id = "1b0219ee-5298-4fef-9927-c2666d9d53fc"
    membership = peri_scribe.models.ComplexMembership(
        fire_identifier=child_id,
        complex_identifier=parent_id,
        complex_name="ROWE CREEK COMPLEX",
    )
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.Fire(
                    name="0445 CROSSWHITE",
                    status=ACTIVE,
                    identifier=child_id,
                ),
            ],
            pathlib.Path("two.gpkg"): [
                peri_scribe.models.Fire(
                    name="Crosswhite",
                    status=ACTIVE,
                    identifier=child_id,
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [membership],
            pathlib.Path("two.gpkg"): [membership],
        },
    )
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=ACTIVE,
            identifier=child_id,
        ),
    ]
    assert fires[0].complex is not None
    assert len(fires[0].complex.fires) == 1


def test_fire_sources_excludes_parent_group_merged_with_unidentified_records(
    stub_fire_reader: StubFireReader,
) -> None:
    parent_id = "b0b0e959-6d11-4831-951a-c464f0f3ab45"
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.Fire(
                    name="CINDER COMPLEX",
                    status=INACTIVE,
                ),
                peri_scribe.models.Fire(
                    name="CINDER COMPLEX",
                    status=INACTIVE,
                    identifier="2026-cabdu-011375",
                ),
                peri_scribe.models.Fire(
                    name="CINDER COMPLEX",
                    status=ACTIVE,
                    identifier=parent_id,
                ),
                peri_scribe.models.Fire(
                    name="5-3",
                    status=ACTIVE,
                    identifier="ef21ead9-ce4d-48f6-964f-46a398857263",
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier="ef21ead9-ce4d-48f6-964f-46a398857263",
                    complex_identifier=parent_id,
                    complex_name="CINDER COMPLEX",
                ),
            ],
        },
    )
    fires = listed_fires(pathlib.Path("sources"))
    assert fires == [
        peri_scribe.models.Fire(
            name="5-3",
            status=ACTIVE,
            identifier="ef21ead9-ce4d-48f6-964f-46a398857263",
        ),
    ]


def test_fire_complexes_skips_membership_for_unidentified_fire(
    stub_fire_reader: StubFireReader,
) -> None:
    parent_id = "b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3"
    child_id = "1b0219ee-5298-4fef-9927-c2666d9d53fc"
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.Fire(
                    name="Crosswhite",
                    status=ACTIVE,
                    identifier=child_id,
                ),
            ],
        },
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.ComplexMembership(
                    fire_identifier="unknown-fire",
                    complex_identifier=parent_id,
                    complex_name="ROWE CREEK COMPLEX",
                ),
                peri_scribe.models.ComplexMembership(
                    fire_identifier=child_id,
                    complex_identifier=parent_id,
                    complex_name="ROWE CREEK COMPLEX",
                ),
            ],
        },
    )
    with structlog.testing.capture_logs() as captured:
        fires = listed_fires(pathlib.Path("sources"))
    assert captured[0]["event"] == (
        "Complex membership references an unidentified fire"
    )
    assert captured[0]["fire_identifier"] == "unknown-fire"
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=ACTIVE,
            identifier=child_id,
        ),
    ]
    assert fires[0].complex is not None
    assert fires[0].complex.fires == frozenset({fires[0]})


def test_fire_sources_propagates_unknown_layer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fire_names(_path: pathlib.Path) -> typing.Never:
        layer_name = "Mystery_Layer_0"
        raise peri_scribe.exceptions.UnknownLayerError(
            layer_name,
            pathlib.Path("fires.gpkg"),
        )

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_names",
        fake_fire_names,
    )
    monkeypatch.setattr(
        peri_scribe.operations,
        "geo_package_files",
        lambda _directory: [pathlib.Path("fires.gpkg")],
    )
    with pytest.raises(
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        listed_fires(pathlib.Path("sources"))


def test_fire_sources_raises_system_exit_for_unreadable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fire_names(_path: pathlib.Path) -> typing.Never:
        message = "no such file"
        raise FileNotFoundError(message)

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_names",
        fake_fire_names,
    )
    monkeypatch.setattr(
        peri_scribe.operations,
        "geo_package_files",
        lambda _directory: [pathlib.Path("fires.gpkg")],
    )
    with pytest.raises(
        SystemExit,
        match=re.escape("Failed to read fires.gpkg: no such file"),
    ):
        listed_fires(pathlib.Path("sources"))


def test_existing_geopackage_filenames_returns_empty_list_without_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: False)
    assert (
        peri_scribe.operations.existing_geopackage_filenames(
            pathlib.Path("/missing"),
        )
        == []
    )


def test_geo_package_files_returns_nested_files_in_sorted_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/data")
    alpha = directory / "sources" / "Alpha_0"
    beta = directory / "sources" / "Beta_0"
    files = [
        beta / "000000,lastEdit=c.gpkg",
        alpha / "000002,lastEdit=b.gpkg",
        alpha / "000001,lastEdit=a.gpkg",
    ]
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(
        pathlib.Path,
        "rglob",
        lambda _self, _pattern: iter(files),
    )
    assert peri_scribe.operations.geo_package_files(directory) == [
        alpha / "000001,lastEdit=a.gpkg",
        alpha / "000002,lastEdit=b.gpkg",
        beta / "000000,lastEdit=c.gpkg",
    ]


def test_geo_package_files_returns_empty_list_without_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: False)
    assert peri_scribe.operations.geo_package_files(pathlib.Path("/missing")) == []


def test_geo_package_files_raises_system_exit_when_tree_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/data")

    def fake_rglob(_self: pathlib.Path, _pattern: str) -> typing.Never:
        message = "denied"
        raise PermissionError(message)

    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(pathlib.Path, "rglob", fake_rglob)
    with pytest.raises(
        SystemExit,
        match=re.escape(f"Failed to read {directory}: denied"),
    ):
        peri_scribe.operations.geo_package_files(directory)


def test_source_geopackage_path_places_watermark_file_under_source_directory() -> None:
    path = peri_scribe.operations.source_geopackage_path(
        pathlib.Path("/base"),
        2026,
        "CA_Perimeters_NIFC_FIRIS_public_view_0",
        17,
        "lastEdit=abc123",
    )
    assert path == pathlib.Path(
        "/base/data/2026/sources/CA_Perimeters_NIFC_FIRIS_public_view_0/"
        "000017,lastEdit=abc123.gpkg",
    )


def test_geopackage_filename_zero_pads_serial_number() -> None:
    assert peri_scribe.operations.geopackage_filename(
        17,
        "lastEdit=abc123",
    ) == pathlib.Path("000017,lastEdit=abc123.gpkg")


def test_parse_geopackage_filename_returns_serial_and_watermark() -> None:
    assert peri_scribe.operations.parse_geopackage_filename(
        pathlib.Path("000017,lastEdit=abc,def.gpkg"),
    ) == (17, "lastEdit=abc,def")


def test_next_serial_number_starts_at_zero_without_existing_files() -> None:
    expected_serial_number = 0
    assert (
        peri_scribe.operations.next_serial_number([], "lastEdit=abc123")
        == expected_serial_number
    )


def test_next_serial_number_increments_beyond_largest_serial() -> None:
    expected_serial_number = 4
    assert (
        peri_scribe.operations.next_serial_number(
            [pathlib.Path("000003,lastEdit=abc123.gpkg")],
            "lastEdit=def456",
        )
        == expected_serial_number
    )


def test_next_serial_number_reuses_serial_for_existing_watermark() -> None:
    expected_serial_number = 3
    assert (
        peri_scribe.operations.next_serial_number(
            [pathlib.Path("000003,lastEdit=abc123.gpkg")],
            "lastEdit=abc123",
        )
        == expected_serial_number
    )


def test_next_serial_number_ignores_malformed_filenames() -> None:
    expected_serial_number = 3
    assert (
        peri_scribe.operations.next_serial_number(
            [
                pathlib.Path("old-style.gpkg"),
                pathlib.Path("000002,lastEdit=abc123.gpkg"),
            ],
            "lastEdit=def456",
        )
        == expected_serial_number
    )


def test_snapshot_path_for_watermark_returns_matching_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/CA_Perimeters_NIFC_FIRIS_public_view_0")
    files = [
        directory / "000017,lastEdit=abc123.gpkg",
        directory / "000018,lastEdit=def789.gpkg",
    ]
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(pathlib.Path, "iterdir", lambda _self: iter(files))
    assert (
        peri_scribe.operations.snapshot_path_for_watermark(
            directory,
            "lastEdit=abc123",
        )
        == directory / "000017,lastEdit=abc123.gpkg"
    )


def test_snapshot_path_for_watermark_returns_none_without_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/CA_Perimeters_NIFC_FIRIS_public_view_0")
    files = [directory / "000017,lastEdit=abc123.gpkg"]
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(pathlib.Path, "iterdir", lambda _self: iter(files))
    assert (
        peri_scribe.operations.snapshot_path_for_watermark(
            directory,
            "lastEdit=other",
        )
        is None
    )


def test_snapshot_path_for_watermark_ignores_malformed_filenames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/CA_Perimeters_NIFC_FIRIS_public_view_0")
    files = [directory / "old-style.gpkg"]
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(pathlib.Path, "iterdir", lambda _self: iter(files))
    assert (
        peri_scribe.operations.snapshot_path_for_watermark(
            directory,
            "lastEdit=abc123",
        )
        is None
    )


UTC = datetime.UTC


def change_feed(
    modified_column: str | None = "ModifiedOnDateTime_dt",
) -> peri_scribe.feed_types.Feed:
    """Return a feed with a known modified column.

    Args:
        modified_column: The modified timestamp column, or None.

    Returns:
        The feed.
    """
    return next(
        peri_scribe.models.build_feeds([
            {
                "feed_type": "ArcGISFeed",
                "url": "https://example.test/ArcGIS/rest/services/Fires/FeatureServer/0",
                "fire_name_column": "name",
                "status_column": "status",
                "modified_column": modified_column,
            },
        ]),
    )


def change_dataframe(
    rows: list[tuple[int, str, tuple[float, float]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame of point features for the given rows.

    Args:
        rows: The OBJECTID, name, and coordinates of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {
            "OBJECTID": [row[0] for row in rows],
            "name": [row[1] for row in rows],
        },
        geometry=[shapely.geometry.Point(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )


def test_parse_iso_datetime_returns_datetime() -> None:
    assert peri_scribe.operations.parse_iso_datetime(
        "2026-01-01T00:00:00",
    ) == datetime.datetime(2026, 1, 1, 0, 0, 0)


def test_parse_iso_datetime_returns_none_for_invalid() -> None:
    assert peri_scribe.operations.parse_iso_datetime("not-a-date") is None


def test_modified_datetime_from_returns_none_for_none() -> None:
    assert peri_scribe.operations.modified_datetime_from(None) is None


def test_modified_datetime_from_returns_none_for_nan() -> None:
    assert peri_scribe.operations.modified_datetime_from(float("nan")) is None


def test_modified_datetime_from_returns_none_for_bool() -> None:
    assert peri_scribe.operations.modified_datetime_from(value=True) is None


def test_modified_datetime_from_returns_none_for_unknown() -> None:
    assert peri_scribe.operations.modified_datetime_from(object()) is None


def test_modified_datetime_from_makes_naive_datetime_utc_aware() -> None:
    result = peri_scribe.operations.modified_datetime_from(
        datetime.datetime(2026, 1, 1, 0, 0, 0),
    )
    assert result == datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_modified_datetime_from_converts_aware_datetime_to_utc() -> None:
    aware = datetime.datetime(
        2026,
        1,
        1,
        12,
        0,
        tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
    )
    result = peri_scribe.operations.modified_datetime_from(aware)
    assert result == datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


def test_modified_datetime_from_parses_iso_string() -> None:
    result = peri_scribe.operations.modified_datetime_from("2026-01-01T00:00:00Z")
    assert result == datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_modified_datetime_from_returns_none_for_invalid_string() -> None:
    assert peri_scribe.operations.modified_datetime_from("nope") is None


def test_modified_datetime_from_parses_epoch_milliseconds() -> None:
    result = peri_scribe.operations.modified_datetime_from(0)
    assert result == datetime.datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_existing_features_returns_none_without_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.operations,
        "existing_geopackage_filenames",
        lambda _directory: [],
    )
    assert (
        peri_scribe.operations.existing_features(pathlib.Path("/sources"), feed) is None
    )


def test_latest_modified_datetime_returns_none_without_existing() -> None:
    feed = change_feed()
    assert peri_scribe.operations.latest_modified_datetime(None, feed) is None


def test_latest_modified_datetime_returns_none_for_empty() -> None:
    feed = change_feed()
    empty = change_dataframe([])
    assert peri_scribe.operations.latest_modified_datetime(empty, feed) is None


def test_latest_modified_datetime_returns_none_without_modified_column() -> None:
    feed = change_feed()
    existing = change_dataframe([(1, "a", (0.0, 0.0))])
    assert peri_scribe.operations.latest_modified_datetime(existing, feed) is None


def test_latest_modified_datetime_returns_maximum() -> None:
    feed = change_feed()
    existing = geopandas.GeoDataFrame(
        {
            "OBJECTID": [1, 2],
            "ModifiedOnDateTime_dt": [
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
            ],
        },
        geometry=[
            shapely.geometry.Point(0.0, 0.0),
            shapely.geometry.Point(1.0, 1.0),
        ],
        crs=pyproj.CRS.from_epsg(4326),
    )
    result = peri_scribe.operations.latest_modified_datetime(existing, feed)
    assert result == datetime.datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)


def test_incremental_cutoff_returns_epoch_without_existing() -> None:
    feed = change_feed()
    assert peri_scribe.operations.incremental_cutoff(
        None,
        feed,
    ) == datetime.datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_incremental_cutoff_subtracts_overlap() -> None:
    feed = change_feed()
    existing = geopandas.GeoDataFrame(
        {
            "OBJECTID": [1],
            "ModifiedOnDateTime_dt": ["2026-01-01T00:10:00Z"],
        },
        geometry=[shapely.geometry.Point(0.0, 0.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    result = peri_scribe.operations.incremental_cutoff(existing, feed)
    assert result == datetime.datetime(2026, 1, 1, 0, 10, 0, tzinfo=UTC) - (
        peri_scribe.operations.OVERLAP
    )


def test_where_clause_for_formats_cutoff() -> None:
    cutoff = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    result = peri_scribe.operations.where_clause_for("ModifiedOnDateTime_dt", cutoff)
    assert result == "ModifiedOnDateTime_dt >= timestamp '2026-01-01T00:00:00Z'"


def test_normalized_attribute_value_returns_none_for_none() -> None:
    assert peri_scribe.operations.normalized_attribute_value(None) is None


def test_normalized_attribute_value_returns_none_for_nan() -> None:
    assert peri_scribe.operations.normalized_attribute_value(float("nan")) is None


def test_normalized_attribute_value_truncates_datetime() -> None:
    result = peri_scribe.operations.normalized_attribute_value(
        datetime.datetime(2026, 1, 1, 0, 0, 0, 123456),
    )
    assert result == datetime.datetime(2026, 1, 1, 0, 0, 0)


def test_normalized_attribute_value_passes_through_other_values() -> None:
    number = 7
    assert peri_scribe.operations.normalized_attribute_value("abc") == "abc"
    assert peri_scribe.operations.normalized_attribute_value(number) == number


def test_attribute_columns_excludes_geometry() -> None:
    new = change_dataframe([(1, "a", (0.0, 0.0))])
    existing = change_dataframe([(1, "a", (0.0, 0.0))])
    assert peri_scribe.operations.attribute_columns(new, existing) == [
        "OBJECTID",
        "name",
    ]


def test_feature_signatures_keys_by_object_id() -> None:
    dataframe = change_dataframe(
        [(1, "a", (0.0, 0.0)), (2, "b", (1.0, 1.0))],
    )
    signatures = peri_scribe.operations.feature_signatures(
        dataframe,
        ["OBJECTID", "name"],
    )
    assert set(signatures) == {1, 2}
    assert signatures[1][0] == (1, "a")
    assert signatures[1][1] == shapely.geometry.Point(0.0, 0.0).wkb


def test_drop_features_already_present_returns_new_when_no_existing() -> None:
    new = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.operations.drop_features_already_present(new, None)
    assert result is new


def test_drop_features_already_present_keeps_new_object_id() -> None:
    new = change_dataframe([(3, "c", (2.0, 2.0))])
    existing = change_dataframe([(1, "a", (0.0, 0.0)), (2, "b", (1.0, 1.0))])
    result = peri_scribe.operations.drop_features_already_present(new, existing)
    assert list(result["OBJECTID"]) == [3]


def test_drop_features_already_present_drops_identical_feature() -> None:
    new = change_dataframe([(1, "a", (0.0, 0.0))])
    existing = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.operations.drop_features_already_present(new, existing)
    assert result.empty


def test_drop_features_already_present_keeps_changed_feature() -> None:
    new = change_dataframe([(1, "changed", (0.0, 0.0))])
    existing = change_dataframe([(1, "a", (0.0, 0.0))])
    result = peri_scribe.operations.drop_features_already_present(new, existing)
    assert list(result["name"]) == ["changed"]


def test_latest_snapshot_path_returns_none_without_files() -> None:
    assert peri_scribe.operations.latest_snapshot_path(pathlib.Path("/d"), []) is None


def test_latest_snapshot_path_returns_last_file() -> None:
    result = peri_scribe.operations.latest_snapshot_path(
        pathlib.Path("/d"),
        [pathlib.Path("000000.gpkg"), pathlib.Path("000001.gpkg")],
    )
    assert result == pathlib.Path("/d/000001.gpkg")


def test_fetch_feed_dataframe_raises_without_modified_column() -> None:
    feed = change_feed(modified_column=None)
    with pytest.raises(ValueError, match="no modified column"):
        peri_scribe.operations.fetch_feed_dataframe(
            feed,
            object(),  # ty: ignore
            [pathlib.Path("000000.gpkg")],
            pathlib.Path("/sources"),
        )


def test_fetch_feed_dataframe_returns_none_without_changed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.operations,
        "existing_features",
        lambda _directory, _feed: None,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        lambda *_arguments, **_keywords: [],
    )
    result = peri_scribe.operations.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [pathlib.Path("000000.gpkg")],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_returns_none_when_dedupe_removes_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.operations,
        "existing_features",
        lambda _directory, _feed: None,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        lambda *_arguments, **_keywords: [1],
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: "feature_set",
    )
    empty = geopandas.GeoDataFrame(
        {"OBJECTID": pd.Series([], dtype="int64"), "name": []},
        geometry=[],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: empty,
    )
    result = peri_scribe.operations.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [pathlib.Path("000000.gpkg")],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_fetches_full_when_directory_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    sentinel = object()
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: "feature_set",
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: sentinel,
    )
    result = peri_scribe.operations.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [],
        pathlib.Path("/sources"),
    )
    assert result is sentinel


def test_fire_sources_collects_paths_for_each_fire(
    stub_fire_reader: StubFireReader,
) -> None:
    one = pathlib.Path("one.gpkg")
    two = pathlib.Path("two.gpkg")
    stub_fire_reader({
        one: [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)],
        two: [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)],
    })
    sources = peri_scribe.operations.fire_sources(pathlib.Path("sources"))
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
    stub_fire_reader({
        path: [
            peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
            peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
        ],
    })
    sources = peri_scribe.operations.fire_sources(pathlib.Path("sources"))
    assert sources == [
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
            paths=(path,),
        ),
    ]


def test_fire_index_entries_sorts_fires_and_paths() -> None:
    sources_directory = pathlib.Path("/index/sources")
    sources = [
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(
                name="zulu",
                status=INACTIVE,
                identifier="z-1",
            ),
            paths=(
                sources_directory / "b.gpkg",
                sources_directory / "a.gpkg",
            ),
        ),
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(name="Alpha", status=ACTIVE),
            paths=(sources_directory / "one.gpkg",),
        ),
    ]
    assert peri_scribe.operations.fire_index_entries(
        sources,
        sources_directory,
    ) == [
        {
            "name": "Alpha",
            "status": "active",
            "identifier": None,
            "complex": None,
            "paths": ["one.gpkg"],
        },
        {
            "name": "zulu",
            "status": "inactive",
            "identifier": "z-1",
            "complex": None,
            "paths": ["a.gpkg", "b.gpkg"],
        },
    ]


def test_fire_document_describes_complex_membership() -> None:
    child = peri_scribe.models.Fire(
        name="Crosswhite",
        status=ACTIVE,
        identifier="child-id",
    )
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="parent-id",
        fires=frozenset({child}),
    )
    assert peri_scribe.operations.fire_document(child) == {
        "name": "Crosswhite",
        "status": "active",
        "identifier": "child-id",
        "complex": {
            "name": "ROWE CREEK COMPLEX",
            "identifier": "parent-id",
        },
    }


def test_year_directory_path_groups_year_under_data() -> None:
    assert peri_scribe.operations.year_directory_path(
        pathlib.Path("/base"),
        2026,
    ) == pathlib.Path("/base/data/2026")


def test_sources_directory_path_places_sources_under_year() -> None:
    assert peri_scribe.operations.sources_directory_path(
        pathlib.Path("/data/2026"),
    ) == pathlib.Path("/data/2026/sources")


def test_fire_index_path_places_index_in_sources_directory() -> None:
    assert peri_scribe.operations.fire_index_path(
        pathlib.Path("/data/2026"),
    ) == pathlib.Path("/data/2026/sources/fires.json")


def test_index_fire_sources_writes_index_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("/index/2026")
    sources = [
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
            paths=(pathlib.Path("/index/2026/sources/one.gpkg"),),
        ),
    ]
    monkeypatch.setattr(
        peri_scribe.operations,
        "fire_sources",
        lambda _directory: sources,
    )
    writes: list[tuple[pathlib.Path, peri_scribe.models.FireIndex]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_fire_index",
        lambda path, document: writes.append((path, document)),
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    peri_scribe.operations.index_fire_sources(year_directory)
    assert writes[0][0] == pathlib.Path("/index/2026/sources/fires.json")
    assert writes[0][1].model_dump() == {
        "version": peri_scribe.operations.FIRE_INDEX_VERSION,
        "fires": [
            {
                "name": "Park Fire",
                "status": "active",
                "identifier": None,
                "complex": None,
                "paths": ["one.gpkg"],
            },
        ],
    }


def test_fire_index_document_wraps_entries_with_version_and_fires_last() -> None:
    entries: list[dict[str, object]] = [
        {
            "name": "Park Fire",
            "status": "active",
            "identifier": None,
            "complex": None,
            "paths": ["one.gpkg"],
        },
    ]
    index = peri_scribe.operations.fire_index_document(entries)
    document = index.model_dump()
    assert list(document) == ["version", "fires"]
    assert document["version"] == peri_scribe.operations.FIRE_INDEX_VERSION
    assert document["fires"] == entries


def test_fire_index_document_rejects_invalid_entry() -> None:
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.operations.fire_index_document([
            {"name": "Park Fire", "status": "exploded", "paths": []},
        ])


def test_load_fire_index_reads_existing_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("/index/2026")
    document = {
        "version": peri_scribe.operations.FIRE_INDEX_VERSION,
        "fires": [
            {
                "name": "Park Fire",
                "status": "active",
                "identifier": None,
                "complex": None,
                "paths": ["one.gpkg"],
            },
        ],
    }
    monkeypatch.setattr(
        peri_scribe.operations,
        "index_fire_sources",
        lambda _year_directory: pytest.fail("index built for existing file"),
    )
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        pathlib.Path,
        "read_text",
        lambda _self, *_arguments, **_keywords: json.dumps(document),
    )
    index = peri_scribe.operations.load_fire_index(year_directory)
    assert index.model_dump() == document


def test_load_fire_index_builds_index_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("/index/2026")
    document = {
        "version": peri_scribe.operations.FIRE_INDEX_VERSION,
        "fires": [],
    }
    built: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.operations,
        "index_fire_sources",
        built.append,
    )
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: False)
    monkeypatch.setattr(
        pathlib.Path,
        "read_text",
        lambda _self, *_arguments, **_keywords: json.dumps(document),
    )
    index = peri_scribe.operations.load_fire_index(year_directory)
    assert built == [year_directory]
    assert index.model_dump() == document


def test_load_fire_index_rejects_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        pathlib.Path,
        "read_text",
        lambda _self, *_arguments, **_keywords: "not json",
    )
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.operations.load_fire_index(pathlib.Path("/index/2026"))
