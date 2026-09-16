"""Isolate sources tests with explicit fixtures."""

from __future__ import annotations

import pathlib
import typing

import pytest

import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.sources.snapshots


if typing.TYPE_CHECKING:
    import tests.helpers.doubles.peri_scribe.fires.sources


@pytest.fixture
def stub_fire_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader:
    """Point the GeoPackage readers at in-memory fires and memberships.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        A function that installs stand-ins serving the given fires and memberships per
        GeoPackage path.
    """

    def stub(
        records_by_path: dict[pathlib.Path, list[peri_scribe.models.FireRecord]],
        memberships_by_path: dict[
            pathlib.Path,
            list[peri_scribe.models.ComplexMembership],
        ]
        | None = None,
    ) -> None:
        """Install fire observations and memberships for isolated reader tests.

        Args:
            records_by_path: Fire observations to serve for each GeoPackage path.
            memberships_by_path: Complex memberships to serve per path, or None for no
                memberships.
        """

        def fake_read_geopackage(
            path: pathlib.Path,
        ) -> peri_scribe.geo.package.GeopackageContents:
            """Serve the configured observations without reading a GeoPackage.

            Args:
                path: Path supplied to the intercepted file operation.

            Returns:
                The fire rows and memberships configured for this path.
            """
            memberships = (memberships_by_path or {}).get(path, [])
            rows = tuple(
                peri_scribe.geo.package.FireRowRecord(
                    record=record,
                    object_id=None,
                    source_name="",
                    attributes={},
                )
                for record in records_by_path.get(path, [])
            )
            return peri_scribe.geo.package.GeopackageContents(
                rows=rows,
                memberships=tuple(memberships),
            )

        def fake_geo_package_files(_directory: pathlib.Path) -> list[pathlib.Path]:
            """Expose the configured snapshot paths to the source reader.

            Args:
                _directory: Directory accepted for reader compatibility; configured
                    paths are used.

            Returns:
                The sorted paths containing configured fires or memberships.
            """
            return sorted(set(records_by_path) | set(memberships_by_path or {}))

        monkeypatch.setattr(
            peri_scribe.geo.package,
            "read_geopackage",
            fake_read_geopackage,
        )
        monkeypatch.setattr(
            peri_scribe.sources.snapshots,
            "geo_package_files",
            fake_geo_package_files,
        )

    return stub
