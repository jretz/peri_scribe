"""Replace gathering dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing

import geopandas

import peri_scribe.areas
import peri_scribe.kml.fire_data
import peri_scribe.kml.selection
import peri_scribe.models
import peri_scribe.report.locations
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import shapely.geometry


def make_plot_option_recorder(
    *,
    render_plots_values: list[bool],
) -> typing.Callable[..., list[peri_scribe.kml.fire_data.FireGeometry]]:
    """Create a callback with controlled dependencies.

    Capture report-stage options without constructing fire geometry.

    Args:
        render_plots_values: Shared list recording whether plot generation was
            requested.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def fire_geometries(
        *args: object,
        scores: peri_scribe.models.FireScores,
        render_plots: bool,
        incident_rows: geopandas.GeoDataFrame | None = None,
        histories: typing.Mapping[
            peri_scribe.kml.selection.AreaKey,
            peri_scribe.areas.PreparedHistory,
        ]
        | None = None,
    ) -> list[peri_scribe.kml.fire_data.FireGeometry]:
        """Capture report-stage options without constructing fire geometry.

        Args:
            args: Unused positional geometry inputs.
            render_plots: Whether the report stage requested image rendering.
            incident_rows: Optional independent incident rows supplied by the stage.
            histories: Prepared area and reporting evidence passed through the stage.
            scores: Saved scores supplied by the report stage.

        Returns:
            An empty fire list for the isolated report-stage assertion.
        """
        render_plots_values.append(render_plots)
        return []

    return fire_geometries


def make_scores_recorder(
    *,
    scores_values: list[peri_scribe.models.FireScores],
) -> typing.Callable[..., list[peri_scribe.kml.fire_data.FireGeometry]]:
    """Create a callback with controlled dependencies.

    Capture report-stage options without constructing fire geometry.

    Args:
        scores_values: Shared list recording score documents supplied to rendering.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def fire_geometries(
        *args: object,
        scores: peri_scribe.models.FireScores,
        render_plots: bool,
        incident_rows: geopandas.GeoDataFrame | None = None,
        histories: typing.Mapping[
            peri_scribe.kml.selection.AreaKey,
            peri_scribe.areas.PreparedHistory,
        ]
        | None = None,
    ) -> list[peri_scribe.kml.fire_data.FireGeometry]:
        """Capture report-stage options without constructing fire geometry.

        Args:
            args: Unused positional geometry inputs.
            render_plots: Whether the report stage requested image rendering.
            incident_rows: Optional independent incident rows supplied by the stage.
            histories: Prepared area and reporting evidence passed through the stage.
            scores: Saved scores supplied by the report stage.

        Returns:
            An empty fire list for the isolated report-stage assertion.
        """
        scores_values.append(scores)
        return []

    return fire_geometries


def make_city_measurement_recorder(
    *,
    measured: list[shapely.Geometry],
) -> typing.Callable[..., peri_scribe.report.locations.NearestCity]:
    """Create a callback with controlled dependencies.

    Observe which geometry is used without consulting a city dataset.

    Args:
        measured: Shared list recording geometries used to find the nearest city.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def nearest_city(
        geometry: shapely.Geometry,
        _cities: geopandas.GeoDataFrame,
    ) -> peri_scribe.report.locations.NearestCity:
        """Observe which geometry is used without consulting a city dataset.

        Args:
            geometry: The fire geometry recorded for the assertion.
            _cities: Unused city data supplied by the caller.

        Returns:
            A fixed city location for the report assertions.
        """
        measured.append(geometry)
        return peri_scribe.report.locations.NearestCity(
            name="Portland",
            state_abbreviation="OR",
            distance=14.6 * units.miles,
            bearing=112.5 * units.degrees,
        )

    return nearest_city


def make_city_layer_reader(
    *,
    calls: list[tuple[pathlib.Path, str]],
) -> typing.Callable[..., geopandas.GeoDataFrame]:
    """Create a callback to isolate derived-layer reads from persistent geography.

    Args:
        calls: Shared list recording dependency calls for assertions.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def read_layer(path: pathlib.Path, layer_name: str) -> geopandas.GeoDataFrame:
        """Isolate derived-layer reads from persistent geography.

        Args:
            path: The requested path, without reading its contents.
            layer_name: The requested history layer.

        Returns:
            The synthetic history frame used by this scenario.
        """
        calls.append((path, layer_name))
        return geopandas.GeoDataFrame()

    return read_layer
