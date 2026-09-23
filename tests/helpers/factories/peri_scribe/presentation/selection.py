"""History rows isolate the source evidence retained during presentation selection."""

from __future__ import annotations

import typing

import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.kml.parsing


if typing.TYPE_CHECKING:
    import geopandas


def perimeter_history(**columns: object) -> geopandas.GeoDataFrame:
    """Provide one valid mapping with optional source provenance columns.

    Args:
        columns: Source values to attach to the perimeter history row.

    Returns:
        A one-row perimeter history for Timber.
    """
    frame = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        (None, "Timber", tests.helpers.factories.geometry.square(1.0)),
    ])
    for column, value in columns.items():
        frame[column] = [value]
    return frame
