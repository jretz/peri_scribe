"""Build authenticated geography generations for reader boundary tests."""

import pathlib

import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.reuse
import spatial_data.layers
import tests.helpers.factories.geography
import tests.helpers.factories.geometry


def publish_full(directory: pathlib.Path, revision: int) -> pathlib.Path:
    """Publish all full-history layers with matching authentication metadata.

    Args:
        directory: Isolated year directory.
        revision: Visible row value distinguishing file generations.

    Returns:
        The full-history file.
    """
    path = peri_scribe.fires.files.history_geopackage_path(directory)
    dataframe = tests.helpers.factories.geography.geo_frame(
        {"revision": [revision]},
        [tests.helpers.factories.geometry.square(0.01)],
    )
    peri_scribe.fires.reuse.write_layers(
        path,
        [
            spatial_data.layers.LayerData(name=name, dataframe=dataframe)
            for name in peri_scribe.fires.files.FULL_LAYER_NAMES
        ],
        generation=str(revision),
    )
    return path


def publish_pair(directory: pathlib.Path, revision: int) -> None:
    """Keep growth rows tied to the exact published full-history file.

    Args:
        directory: Isolated year directory.
        revision: Visible row value shared by every layer in the pair.
    """
    full_path = publish_full(directory, revision)
    dataframe = tests.helpers.factories.geography.geo_frame(
        {"revision": [revision]},
        [tests.helpers.factories.geometry.square(0.01)],
    )
    peri_scribe.fires.reuse.write_layers(
        peri_scribe.fires.differential.differential_geopackage_path(directory),
        [
            spatial_data.layers.LayerData(name=name, dataframe=dataframe)
            for name in (
                peri_scribe.fires.files.PERIMETER_LAYER_NAME,
                peri_scribe.fires.files.POINT_LAYER_NAME,
            )
        ],
        generation=peri_scribe.fires.differential.differential_generation(
            full_path,
            directory,
        ),
    )
