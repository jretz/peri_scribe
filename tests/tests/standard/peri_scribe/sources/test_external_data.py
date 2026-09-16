"""Tests for peri_scribe.sources.external_data."""

from __future__ import annotations

import dataclasses

import pytest

import peri_scribe.sources.external_data
import peri_scribe.sources.external_sources
import tests.helpers.doubles.peri_scribe.sources.external_sources


def test_output_path_places_single_file_under_sources() -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=(),
        combine=False,
        compact_database=False,
    )
    path = peri_scribe.sources.external_data.output_path(
        tests.helpers.doubles.peri_scribe.sources.external_sources.YEAR_DIRECTORY,
        source,
    )
    assert (
        path
        == tests.helpers.doubles.peri_scribe.sources.external_sources.YEAR_DIRECTORY
        / "sources"
        / "buildings.gpkg"
    )


def test_output_path_names_compact_buildings_database() -> None:
    path = peri_scribe.sources.external_data.output_path(
        tests.helpers.doubles.peri_scribe.sources.external_sources.YEAR_DIRECTORY,
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
    )
    assert (
        path
        == tests.helpers.doubles.peri_scribe.sources.external_sources.YEAR_DIRECTORY
        / "sources"
        / "buildings.sqlite"
    )


def test_output_path_raises_for_combined_source_with_state() -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California", "Texas"),
        combine=True,
        compact_database=False,
    )
    with pytest.raises(ValueError, match="combines its states"):
        peri_scribe.sources.external_data.output_path(
            tests.helpers.doubles.peri_scribe.sources.external_sources.YEAR_DIRECTORY,
            source,
            state="California",
        )


def test_output_path_names_live_arcgis_source() -> None:
    path = peri_scribe.sources.external_data.output_path(
        tests.helpers.doubles.peri_scribe.sources.external_sources.YEAR_DIRECTORY,
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    )
    assert (
        path
        == tests.helpers.doubles.peri_scribe.sources.external_sources.YEAR_DIRECTORY
        / "sources"
        / "evacuations.gpkg"
    )


def test_output_path_names_per_state_geopackage() -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        combine=False,
        compact_database=False,
    )
    path = peri_scribe.sources.external_data.output_path(
        tests.helpers.doubles.peri_scribe.sources.external_sources.YEAR_DIRECTORY,
        source,
        state="California",
    )
    assert (
        path
        == tests.helpers.doubles.peri_scribe.sources.external_sources.YEAR_DIRECTORY
        / "sources"
        / "buildings"
        / "California.gpkg"
    )
