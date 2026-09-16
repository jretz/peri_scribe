"""Verify fire identities, complex membership, and model validation."""

from __future__ import annotations

import datetime
import zoneinfo

import hypothesis
import hypothesis.strategies
import pytest

import peri_scribe.models
import tests.peri_scribe.models_helpers


@hypothesis.given(
    identifiers=tests.peri_scribe.models_helpers.identifier_collections(),
)
def test_canonical_fire_identifier_accepts_single_pass_iterators(
    identifiers: list[str],
) -> None:
    assert peri_scribe.models.canonical_fire_identifier(iter(identifiers)) == (
        peri_scribe.models.canonical_fire_identifier(identifiers)
    )


@pytest.mark.parametrize(
    "identifier",
    ["00000000-0000-0000-0000-000000000000", "other"],
)
def test_canonical_fire_identifier_preserves_iterator_fallbacks(
    identifier: str,
) -> None:
    assert (
        peri_scribe.models.canonical_fire_identifier(iter([identifier])) == identifier
    )


@hypothesis.given(scenario=tests.peri_scribe.models_helpers.clock_change_comparisons())
def test_times_are_contemporaneous_is_independent_of_time_zone_representation(
    scenario: tuple[datetime.datetime, datetime.datetime, datetime.timedelta],
) -> None:
    left, right, tolerance = scenario
    expected = peri_scribe.models.times_are_contemporaneous(
        left.astimezone(datetime.UTC),
        right.astimezone(datetime.UTC),
        tolerance,
    )
    assert (
        peri_scribe.models.times_are_contemporaneous(left, right, tolerance) == expected
    )


@pytest.mark.parametrize(
    ("left", "right", "tolerance", "expected"),
    [
        (
            datetime.datetime(2026, 3, 8, 9, 5, tzinfo=datetime.UTC),
            datetime.datetime(2026, 3, 8, 10, tzinfo=datetime.UTC),
            datetime.timedelta(minutes=55),
            True,
        ),
        (
            datetime.datetime(2026, 11, 1, 8, tzinfo=datetime.UTC),
            datetime.datetime(2026, 11, 1, 9, tzinfo=datetime.UTC),
            datetime.timedelta(0),
            False,
        ),
    ],
    ids=["skipped-hour", "repeated-hour"],
)
def test_times_are_contemporaneous_uses_elapsed_time_across_clock_changes(
    left: datetime.datetime,
    right: datetime.datetime,
    tolerance: datetime.timedelta,
    *,
    expected: bool,
) -> None:
    zone = zoneinfo.ZoneInfo("America/Los_Angeles")
    assert (
        peri_scribe.models.times_are_contemporaneous(
            left.astimezone(zone),
            right.astimezone(zone),
            tolerance,
        )
        == expected
    )


def test_times_are_contemporaneous_accepts_naive_times() -> None:
    left = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC).replace(tzinfo=None)
    right = left + datetime.timedelta(hours=1)
    assert peri_scribe.models.times_are_contemporaneous(
        left,
        right,
        datetime.timedelta(hours=1),
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_times_are_contemporaneous_rejects_mixed_naive_and_aware_times(
    *,
    reverse: bool,
) -> None:
    aware = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
    naive = aware.replace(tzinfo=None)
    left, right = (aware, naive) if reverse else (naive, aware)
    with pytest.raises(TypeError, match="offset-naive and offset-aware"):
        peri_scribe.models.times_are_contemporaneous(left, right, datetime.timedelta(0))


@hypothesis.given(name=hypothesis.infer)
def test_normalize_fire_name_is_idempotent(name: str) -> None:
    normalized = peri_scribe.models.normalize_fire_name(name)
    assert peri_scribe.models.normalize_fire_name(normalized) == normalized


@hypothesis.given(
    identifiers=hypothesis.strategies.lists(hypothesis.strategies.text(), max_size=20),
    data=hypothesis.strategies.data(),
)
def test_canonical_fire_identifier_ignores_order_and_duplicates(
    identifiers: list[str],
    data: hypothesis.strategies.DataObject,
) -> None:
    reordered = data.draw(hypothesis.strategies.permutations(identifiers))
    assert peri_scribe.models.canonical_fire_identifier(
        [*reordered, *identifiers],
    ) == peri_scribe.models.canonical_fire_identifier(identifiers)


def test_fire_complex_links_fires_circularly() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    fire_complex = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({fire}),
    )
    assert fire.complex is fire_complex
    assert fire_complex.fires == frozenset({fire})
    assert next(iter(fire_complex.fires)).complex is fire_complex


def test_fire_complex_does_not_link_when_it_has_no_fires() -> None:
    fire_complex = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset(),
    )
    assert fire_complex.fires == frozenset()


def test_fire_equality_ignores_complex() -> None:
    left_fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    right_fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({left_fire}),
    )
    peri_scribe.models.FireComplex(
        name="HAY CREEK COMPLEX",
        identifier="851ddf21-4ead-4835-b54b-b3cf7bd6ac21",
        fires=frozenset({right_fire}),
    )
    assert left_fire == right_fire


def test_fire_hash_ignores_complex() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    hash_before = hash(fire)
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({fire}),
    )
    assert hash(fire) == hash_before
    assert fire == peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )


def test_fire_complex_equality() -> None:
    left = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({
            peri_scribe.models.Fire(
                name="Crosswhite",
                status=peri_scribe.models.FireStatus.ACTIVE,
            ),
        }),
    )
    right = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({
            peri_scribe.models.Fire(
                name="Crosswhite",
                status=peri_scribe.models.FireStatus.ACTIVE,
            ),
        }),
    )
    assert left == right


def test_fire_complex_repr_does_not_recurse() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    fire_complex = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({fire}),
    )
    assert "ROWE CREEK COMPLEX" in repr(fire_complex)
    assert "Crosswhite" in repr(fire_complex)
    assert "complex" not in repr(fire)


def test_is_globally_unique_identifier() -> None:
    assert peri_scribe.models.is_globally_unique_identifier(
        "286b7f1d-8945-4a5d-9d81-5235c18af1fe",
    )
    assert not peri_scribe.models.is_globally_unique_identifier("2026-nvccd-030683")
    assert not peri_scribe.models.is_globally_unique_identifier("not-a-guid")


def test_is_unique_fire_identifier() -> None:
    assert peri_scribe.models.is_unique_fire_identifier("2026-nvccd-030683")
    assert not peri_scribe.models.is_unique_fire_identifier(
        "286b7f1d-8945-4a5d-9d81-5235c18af1fe",
    )
    assert not peri_scribe.models.is_unique_fire_identifier("z-1")


def test_canonical_fire_identifier_prefers_unique_then_guid_then_other() -> None:
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    unique = "2026-nvccd-030683"
    assert peri_scribe.models.canonical_fire_identifier({unique, guid}) == unique
    assert peri_scribe.models.canonical_fire_identifier({guid}) == guid
    assert peri_scribe.models.canonical_fire_identifier({"z-1"}) == "z-1"
    assert peri_scribe.models.canonical_fire_identifier(set()) is None


def test_normalize_fire_name_treats_separators_as_spaces() -> None:
    assert peri_scribe.models.normalize_fire_name("  Park   FIRE ") == "park fire"
    assert peri_scribe.models.normalize_fire_name("SANTA-ROSA") == "santa rosa"
    assert peri_scribe.models.normalize_fire_name("3-1") == "3 1"


def test_fire_aliases_default_to_empty() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    assert fire.aliases == frozenset()
