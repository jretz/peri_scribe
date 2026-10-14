"""Replace classification dependencies with controlled test doubles."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import shapely.affinity


def make_union_recorder(
    *,
    union_inputs: list[list[shapely.Geometry]],
    original_union_all: typing.Callable[..., shapely.Geometry],
) -> typing.Callable[..., shapely.Geometry]:
    """Return a recorder of union inputs for observation deduplication checks.

    Args:
        union_inputs: Shared list recording the geometries supplied to each union.
        original_union_all: Original union operation used to preserve geometric results.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def recording_union_all(geometries: list[shapely.Geometry]) -> shapely.Geometry:
        """Capture union inputs to verify observation deduplication.

        Args:
            geometries: Geometries supplied to the union operation.

        Returns:
            The union of the supplied geometries.
        """
        union_inputs.append(list(geometries))
        return original_union_all(geometries)

    return recording_union_all


def make_reproject_recorder(
    *,
    reprojected: list[tuple[int, bytes]],
    original: typing.Callable[..., shapely.Geometry],
) -> typing.Callable[..., shapely.Geometry]:
    """Return a recorder of projection inputs for source-specific geometry checks.

    Args:
        reprojected: Shared list recording source references and input geometry bytes.
        original: Original operation whose results the callback preserves.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def recording_reproject(geometry: shapely.Geometry, wkid: int) -> shapely.Geometry:
        """Capture reprojection inputs to verify source-specific geometry handling.

        Args:
            geometry: Geometry supplied for the selected spatial case.
            wkid: Identifier of the geometry's source coordinate system.

        Returns:
            The geometry projected into California Albers.
        """
        reprojected.append((wkid, geometry.wkb))
        return original(geometry, wkid)

    return recording_reproject
