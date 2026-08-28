"""Output operations for peri_scribe."""

import json
import pathlib
import shutil
from typing import TYPE_CHECKING

import matplotlib.backends.backend_agg
import matplotlib.figure
import seaborn as sns
import structlog


if TYPE_CHECKING:
    import peri_scribe.models


logger = structlog.get_logger()


DATA_DIRECTORY = pathlib.Path("data")


def write_geopackage(
    path: pathlib.Path,
    layers: list[peri_scribe.models.LayerData],
) -> None:
    if path.exists():
        path.unlink()
        logger.debug("Replaced existing", path=path.name)
    mode = "w"
    for layer_data in layers:
        layer_data.dataframe.to_file(
            path,
            driver="GPKG",
            layer=layer_data.name,
            mode=mode,
        )
        logger.debug(
            "Wrote layer",
            layer=layer_data.name,
            features=len(layer_data.dataframe),
        )
        mode = "a"


def remove_directory_tree(path: pathlib.Path) -> None:
    """Remove *path* and everything under it, when it is a directory.

    Args:
        path: The directory tree to remove.
    """
    if path.is_dir():
        shutil.rmtree(path)


def write_fire_index(
    path: pathlib.Path,
    document: peri_scribe.models.FireIndex,
) -> None:
    """Write *document* to *path* as pretty-printed JSON.

    Args:
        path: The JSON file to write.
        document: The validated fire index to serialize.
    """
    with path.open("w", encoding="utf-8") as file:
        json.dump(document.model_dump(mode="json"), file, indent=4)
    logger.debug("Wrote fire index", path=path.name, fires=len(document.fires))


def write_fire_scores(
    path: pathlib.Path,
    document: peri_scribe.models.FireScores,
) -> None:
    """Write *document* to *path* as pretty-printed JSON.

    Args:
        path: The JSON file to write.
        document: The validated fire scores to serialize.
    """
    with path.open("w", encoding="utf-8") as file:
        json.dump(document.model_dump(mode="json"), file, indent=4)
    logger.debug("Wrote fire scores", path=path.name, fires=len(document.fires))


def write_fire_scores_histogram(
    path: pathlib.Path,
    document: peri_scribe.models.FireScores,
) -> None:
    """Write *document*'s scores to *path* as a discrete score histogram.

    Each score the fires have reached gets one bar whose height is the number of fires
    with that score.

    Args:
        path: The PNG file to write.
        document: The validated fire scores to plot.
    """
    figure = matplotlib.figure.Figure()
    matplotlib.backends.backend_agg.FigureCanvasAgg(figure)
    axes = figure.subplots()
    sns.histplot(
        [entry.score for entry in document.fires],
        discrete=True,
        ax=axes,
    )
    axes.set_xlabel("Score")
    axes.set_ylabel("Fires")
    figure.savefig(path)
    logger.debug("Wrote fire scores histogram", path=path.name)


def configure_logging(log_level: str) -> None:
    """Configure structlog with the minimum log level."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%S%z", utc=False),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )
