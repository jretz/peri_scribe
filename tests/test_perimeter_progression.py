"""Tests for peri_scribe.perimeter_progression."""

from __future__ import annotations

import datetime

import pytest
import shapely.geometry

import peri_scribe.perimeter_progression


def ring(
    geometry: shapely.Geometry,
    observation_time: datetime.datetime | None = None,
) -> peri_scribe.perimeter_progression.Ring:
    """Build a growth ring with *geometry* and *observation_time*.

    Args:
        geometry: The ring geometry.
        observation_time: The ring's observation time, or None.

    Returns:
        The ring.
    """
    return peri_scribe.perimeter_progression.Ring(
        geometry=geometry,
        observation_time=observation_time,
    )


def square(side: float) -> shapely.geometry.Polygon:
    """Return a square of the given side, centered at the origin.

    Args:
        side: The length of each side.

    Returns:
        The square.
    """
    half = side / 2
    return shapely.geometry.box(-half, -half, half, half)


def band(name: str) -> peri_scribe.perimeter_progression.ProgressionBand:
    """Return the shared progression band named *name*.

    Args:
        name: The band name.

    Returns:
        The band.
    """
    for candidate in peri_scribe.perimeter_progression.PROGRESSION_BANDS:
        if candidate.name == name:
            return candidate
    pytest.fail(f"No band named {name!r}")


def test_ring_date_converts_to_california_date() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.perimeter_progression.ring_date(observation_time) == (
        datetime.date(2026, 8, 5)
    )


def test_band_for_age_covers_every_age() -> None:
    assert peri_scribe.perimeter_progression.band_for_age(0) is band("Latest Day")
    assert peri_scribe.perimeter_progression.band_for_age(1) is band(
        "2 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(2) is band(
        "2 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(3) is band(
        "4 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(6) is band(
        "4 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(7) is band(
        "8 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(14) is band(
        "8 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(15) is band(
        "16 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(30) is band(
        "16 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(31) is band(
        "32 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(62) is band(
        "32 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(63) is band(
        "64 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(126) is band(
        "64 Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(127) is band(
        "128+ Days Before That",
    )
    assert peri_scribe.perimeter_progression.band_for_age(365) is band(
        "128+ Days Before That",
    )


def test_band_for_age_returns_none_without_band() -> None:
    assert peri_scribe.perimeter_progression.band_for_age(-1) is None


def test_band_label_names_single_date() -> None:
    latest_date = datetime.date(2026, 8, 15)
    assert (
        peri_scribe.perimeter_progression.band_label(
            band("Latest Day"),
            latest_date,
            [datetime.date(2026, 8, 15)],
        )
        == "08/15"
    )


def test_band_label_names_actual_date_range() -> None:
    latest_date = datetime.date(2026, 8, 15)
    assert (
        peri_scribe.perimeter_progression.band_label(
            band("2 Days Before That"),
            latest_date,
            [
                datetime.date(2026, 8, 13),
                datetime.date(2026, 8, 14),
            ],
        )
        == "08/13 - 08/14"
    )


def test_band_label_names_partial_range_without_full_window() -> None:
    latest_date = datetime.date(2026, 8, 15)
    assert (
        peri_scribe.perimeter_progression.band_label(
            band("8 Days Before That"),
            latest_date,
            [
                datetime.date(2026, 8, 6),
                datetime.date(2026, 8, 8),
            ],
        )
        == "08/06 - 08/08"
    )


def test_band_label_names_open_ended_band_by_boundary() -> None:
    latest_date = datetime.date(2026, 8, 15)
    assert (
        peri_scribe.perimeter_progression.band_label(
            band("128+ Days Before That"),
            latest_date,
            [datetime.date(2026, 4, 5)],
        )
        == "≤ 04/10"
    )


def test_progression_bands_groups_rings_into_bands() -> None:
    bands = peri_scribe.perimeter_progression.progression_bands(
        (
            ring(
                square(1.0),
                datetime.datetime(2026, 8, 13, 20, 0, tzinfo=datetime.UTC),
            ),
            ring(
                square(2.0),
                datetime.datetime(2026, 8, 14, 20, 0, tzinfo=datetime.UTC),
            ),
            ring(
                square(3.0),
                datetime.datetime(2026, 8, 15, 20, 0, tzinfo=datetime.UTC),
            ),
        ),
    )
    assert [(band.name, band.label) for band in bands] == [
        ("Latest Day", "08/15"),
        ("2 Days Before That", "08/13 - 08/14"),
    ]
    latest, two_days = bands
    assert latest.geometry.equals(square(3.0))
    assert two_days.geometry.equals(square(2.0))


def test_progression_bands_skips_bands_without_rings() -> None:
    bands = peri_scribe.perimeter_progression.progression_bands(
        (
            ring(
                square(1.0),
                datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
            ),
            ring(
                square(2.0),
                datetime.datetime(2026, 8, 15, 20, 0, tzinfo=datetime.UTC),
            ),
        ),
    )
    assert [(band.name, band.label) for band in bands] == [
        ("Latest Day", "08/15"),
        ("8 Days Before That", "08/05"),
    ]


def test_progression_bands_skips_bands_with_empty_union() -> None:
    bands = peri_scribe.perimeter_progression.progression_bands(
        (
            ring(
                shapely.geometry.Polygon(),
                datetime.datetime(2026, 8, 13, 20, 0, tzinfo=datetime.UTC),
            ),
            ring(
                square(1.0),
                datetime.datetime(2026, 8, 15, 20, 0, tzinfo=datetime.UTC),
            ),
        ),
    )
    assert [(band.name, band.label) for band in bands] == [
        ("Latest Day", "08/15"),
    ]


def test_progression_bands_skips_undated_rings() -> None:
    assert (
        peri_scribe.perimeter_progression.progression_bands(
            (ring(square(1.0)),),
        )
        == ()
    )


def test_progression_bands_returns_nothing_without_rings() -> None:
    assert peri_scribe.perimeter_progression.progression_bands(()) == ()
