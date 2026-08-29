"""Output operations for peri_scribe."""

import json
import pathlib
import shutil
from typing import TYPE_CHECKING

import matplotlib.backends.backend_agg
import matplotlib.figure
import numpy as np
import seaborn as sns
import structlog


if TYPE_CHECKING:
    import peri_scribe.models


logger = structlog.get_logger()


DATA_DIRECTORY = pathlib.Path("data")

# The figure size of the fire-scores chart, in inches at the default resolution.
FIRE_SCORES_CHART_SIZE_IN_INCHES = (10.24, 7.68)


def curve_knees(scores: list[int]) -> list[tuple[int, float]]:
    """Return the (score, complementary share) pairs where the CCDF bends most.

    The curve is the complementary share plotted with a logarithmic y-axis, so the fit
    is over (score, log share) coordinates. The two knees are the breakpoints of the
    three-line-segment fit with the smallest total squared error; fewer than five
    visible points leaves no room for two breakpoints.

    Args:
        scores: Every fire's score.

    Returns:
        The knee points as (score, complementary share) pairs, in score order.
    """
    values, counts = np.unique(scores, return_counts=True)
    total = len(scores)
    shares = (total - np.cumsum(counts)) / total
    visible = shares > 0
    values, shares = values[visible], shares[visible]
    points = np.column_stack((values, np.log10(shares)))

    def fit_error(first: int, second: int) -> float:
        error = 0.0
        for low, high in ((0, first), (first, second), (second, len(points))):
            segment = points[low : high + 1]
            x, y = segment[:, 0], segment[:, 1]
            design = np.column_stack((x, np.ones(len(x))))
            coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
            error += float(np.sum((y - design @ coefficients) ** 2))
        return error

    best = None
    for first in range(2, len(points) - 2):
        for second in range(first + 2, len(points)):
            error = fit_error(first, second)
            if best is None or error < best[0]:
                best = (error, first, second)
    if best is None:
        return []
    _, first, second = best
    return [
        (int(values[first]), float(shares[first])),
        (int(values[second]), float(shares[second])),
    ]


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


def write_fire_scores_ccdf(
    path: pathlib.Path,
    document: peri_scribe.models.FireScores,
) -> None:
    """Write *document*'s scores to *path* as a complementary CDF plot.

    Each point shows the share of fires whose score exceeds that score. The y-axis is
    logarithmic because that share spans several orders of magnitude. The knees of the
    curve are labeled with their score and percentile; a failure to find or label the
    knees is logged and the plot is still written.

    Args:
        path: The PNG file to write.
        document: The validated fire scores to plot.
    """
    figure = matplotlib.figure.Figure(
        figsize=FIRE_SCORES_CHART_SIZE_IN_INCHES,
    )
    matplotlib.backends.backend_agg.FigureCanvasAgg(figure)
    axes = figure.subplots()
    sns.ecdfplot(
        [entry.score for entry in document.fires],
        complementary=True,
        ax=axes,
    )
    axes.set_yscale("log")
    axes.set_xlabel("Score")
    axes.set_ylabel("Complementary CDF")
    try:
        knees = curve_knees([entry.score for entry in document.fires])
        for score, share in knees:
            percentile = (1 - share) * 100
            axes.annotate(
                f"score {score}\npercentile {percentile:.1f}",
                xy=(score, share),
                xytext=(8, 8),
                textcoords="offset points",
                arrowprops={"arrowstyle": "-", "color": "0.3"},
            )
    except Exception:
        logger.exception("Skipped fire scores knee labels")
    figure.savefig(path)
    logger.debug("Wrote fire scores ccdf", path=path.name)


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
