"""Tests for peri_scribe.operations."""

import pathlib
import re
import typing

import pytest
import structlog

import peri_scribe.exceptions
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.operations


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

    return stub


def test_list_fires_prefers_most_common_mixed_case_spelling(
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
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)]


def test_list_fires_uses_most_common_spelling_when_none_is_mixed_case(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="PARK FIRE", status=INACTIVE),
            peri_scribe.models.Fire(name="park fire", status=INACTIVE),
            peri_scribe.models.Fire(name="park fire", status=INACTIVE),
        ],
    })
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [peri_scribe.models.Fire(name="park fire", status=INACTIVE)]


def test_list_fires_breaks_mixed_case_ties_by_first_spelling(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
            peri_scribe.models.Fire(name="PARK Fire", status=ACTIVE),
        ],
    })
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)]


def test_list_fires_marks_fire_active_when_any_record_is_active(
    stub_fire_reader: StubFireReader,
) -> None:
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="ALTA", status=INACTIVE),
            peri_scribe.models.Fire(name="Alta", status=ACTIVE),
        ],
    })
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [peri_scribe.models.Fire(name="Alta", status=ACTIVE)]


def test_list_fires_merges_names_across_files(
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
    fires = peri_scribe.operations.list_fires(
        (pathlib.Path("one.gpkg"), pathlib.Path("two.gpkg")),
    )
    assert fires == [
        peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
        peri_scribe.models.Fire(name="ALTA", status=INACTIVE),
        peri_scribe.models.Fire(name="Creek Fire", status=ACTIVE),
    ]


def test_list_fires_merges_records_with_same_identifier_under_different_names(
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
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=ACTIVE,
            identifier=crosswhite_id,
        ),
    ]


def test_list_fires_keeps_same_named_fires_with_different_identifiers_separate(
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
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
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


def test_list_fires_merges_unidentified_records_with_same_named_identified_records(
    stub_fire_reader: StubFireReader,
) -> None:
    # The CA layer's FIRIS records carry no identifier; the WFIGS records for the
    # same fire do. All of them are the same fire (Bug).
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="BUG", status=INACTIVE, identifier=None),
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
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [
        peri_scribe.models.Fire(
            name="Bug",
            status=ACTIVE,
            identifier="2026-nvccd-030683",
        ),
    ]


def test_list_fires_merges_keyed_record_with_later_unidentified_same_named_record(
    stub_fire_reader: StubFireReader,
) -> None:
    bug_id = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    stub_fire_reader({
        pathlib.Path("one.gpkg"): [
            peri_scribe.models.Fire(name="Bug", status=ACTIVE, identifier=bug_id),
            peri_scribe.models.Fire(name="BUG", status=INACTIVE, identifier=None),
        ],
    })
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [
        peri_scribe.models.Fire(name="Bug", status=ACTIVE, identifier=bug_id),
    ]


def test_list_fires_merges_identified_records_through_a_shared_unidentified_record(
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
            peri_scribe.models.Fire(name="BUG", status=INACTIVE, identifier=None),
            peri_scribe.models.Fire(
                name="Bug",
                status=ACTIVE,
                identifier="2026-nvccd-030683",
            ),
        ],
    })
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
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
        peri_scribe.models.Fire(name="Bug", status=ACTIVE, identifier=None),
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


def test_list_fires_excludes_complex_parents(
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
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [
        peri_scribe.models.Fire(
            name="0445 CROSSWHITE",
            status=ACTIVE,
            identifier=child_id,
        ),
    ]


def test_list_fires_links_member_fires_to_their_complex(
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
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    fire = fires[0]
    assert fire.complex is not None
    assert fire.complex.name == "ROWE CREEK COMPLEX"
    assert fire.complex.identifier == parent_id
    assert fire.complex.fires == frozenset({fire})
    assert next(iter(fire.complex.fires)).complex is fire.complex


def test_list_fires_builds_one_complex_from_memberships_across_files(
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
    fires = peri_scribe.operations.list_fires(
        (pathlib.Path("one.gpkg"), pathlib.Path("two.gpkg")),
    )
    assert fires == [
        peri_scribe.models.Fire(
            name="Crosswhite",
            status=ACTIVE,
            identifier=child_id,
        ),
    ]
    assert fires[0].complex is not None
    assert len(fires[0].complex.fires) == 1


def test_list_fires_excludes_parent_group_merged_with_unidentified_records(
    stub_fire_reader: StubFireReader,
) -> None:
    parent_id = "b0b0e959-6d11-4831-951a-c464f0f3ab45"
    stub_fire_reader(
        {
            pathlib.Path("one.gpkg"): [
                peri_scribe.models.Fire(
                    name="CINDER COMPLEX",
                    status=INACTIVE,
                    identifier=None,
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
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
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
        fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
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


def test_list_fires_propagates_unknown_layer_error(
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
    with pytest.raises(
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        peri_scribe.operations.list_fires((pathlib.Path("fires.gpkg"),))


def test_list_fires_raises_system_exit_for_unreadable_file(
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
    with pytest.raises(
        SystemExit,
        match=re.escape("Failed to read fires.gpkg: no such file"),
    ):
        peri_scribe.operations.list_fires((pathlib.Path("fires.gpkg"),))
