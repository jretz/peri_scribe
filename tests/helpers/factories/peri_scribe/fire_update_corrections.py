"""Publish corrected mapping through the same provenance path as a KMZ build."""

import datetime

import geopandas
import shapely

import peri_scribe.fires.history
import peri_scribe.models
import peri_scribe.perimeters.versions
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.selection
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.peri_scribe.perimeters.versions


def observations() -> list[peri_scribe.perimeters.versions.SourceObservation]:
    """Provide a downward correction whose replacement keeps the superseded source.

    Returns:
        Mapping publications five minutes apart with 99.5 percent footprint overlap.
    """
    timestamp = datetime.datetime(2026, 9, 23, 18, tzinfo=datetime.UTC)
    return [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=shapely.box(-121.5, 36.2, -121.4 - number * 0.0005, 36.3),
            observation_time=timestamp + datetime.timedelta(minutes=5 * number),
            snapshot_time=timestamp + datetime.timedelta(minutes=5 * number),
            serial_number=number + 1,
            object_id=number + 10,
            source_file=f"mapping-{number}.gpkg",
            attributes={
                "source": "CAL FIRE INTEL FLIGHT DATA",
                "type": "Heat Perimeter",
            },
        )
        for number in range(2)
    ]


def summary(
    observations: list[peri_scribe.perimeters.versions.SourceObservation],
) -> peri_scribe.presentation.fire_data.FireSummary:
    """Preserve source evidence while presenting the current reconciled mapping.

    Args:
        observations: Source publications before history reconciliation.

    Returns:
        One name-only fire with a report-eligible Type 1 designation.
    """
    fire = peri_scribe.models.Fire(
        name="Timber",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    rows = [
        peri_scribe.fires.history.perimeter_row(fire, None, observation)
        for observation in peri_scribe.perimeters.versions.collapse_mapping_revisions(
            observations,
        )
    ]
    perimeters = geopandas.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    points = geopandas.GeoDataFrame(
        {
            "fire_name": [fire.name],
            "fire_identifier": [None],
            "source_attributes": ['{"IncidentComplexityLevel": "Type 1 Incident"}'],
        },
        geometry=[shapely.Point(-121.45, 36.25)],
        crs="EPSG:4326",
    )
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            fire.name,
            "active",
        ),
    ])
    histories = peri_scribe.presentation.selection.prepare_histories(perimeters, points)
    (prepared,) = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        perimeters,
        points,
        perimeters.iloc[0:0],
        histories=histories,
    )
    return prepared
