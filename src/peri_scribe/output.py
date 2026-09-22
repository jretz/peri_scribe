"""Output operations for peri_scribe."""

from __future__ import annotations

import json
import pathlib
import shutil
import typing

import pydantic
import structlog

import svg_charts.distribution


if typing.TYPE_CHECKING:
    import peri_scribe.models


logger = structlog.get_logger()


CCDF_TITLE = "Fire score distribution"
CCDF_Y_AXIS_LABEL = "Complementary CDF"
CCDF_X_AXIS_LABEL = "Score"


def ccdf_svg(document: peri_scribe.models.FireScores) -> str:
    """Present fire scores with their distribution knees and percentile labels.

    Args:
        document: The validated fire scores to plot.

    Returns:
        The SVG document text, including the chart when knee detection fails.
    """
    scores = [entry.score for entry in document.fires]
    try:
        knees = svg_charts.distribution.curve_knees(scores)
    except Exception:
        logger.exception("Skipped fire scores knee labels")
        knees = []
    return svg_charts.distribution.draw_ccdf(
        scores,
        title=CCDF_TITLE,
        x_axis_label=CCDF_X_AXIS_LABEL,
        y_axis_label=CCDF_Y_AXIS_LABEL,
        annotations=tuple(
            svg_charts.distribution.CurveAnnotation(
                value=score,
                share=share,
                lines=(f"score {score:g}", f"percentile {(1 - share) * 100:.1f}"),
            )
            for score, share in knees
        ),
    )


def ccdf_html(document: peri_scribe.models.FireScores) -> str:
    """Return *document*'s scores as an HTML page holding an inline SVG chart.

    The chart is inline rather than referenced so the file stands alone: it can be
    opened, mailed, or served without the chart going missing.

    Args:
        document: The validated fire scores to plot.

    Returns:
        The HTML page.
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>PeriScribe fire scores</title>\n"
        "</head>\n"
        "<body>\n"
        f"{ccdf_svg(document)}\n"
        "</body>\n"
        "</html>\n"
    )


def remove_directory_tree(path: pathlib.Path) -> None:
    """Remove *path* and everything under it, when it is a directory.

    Args:
        path: The directory tree to remove.
    """
    if path.is_dir():
        shutil.rmtree(path)


def write_document(
    path: pathlib.Path,
    document: peri_scribe.models.FireIndex | peri_scribe.models.FireScores,
) -> None:
    """Write *document* to *path* as pretty-printed JSON.

    The fire index and the fire scores are both versioned documents holding the season's
    fires, so they share one on-disk shape and one writer.

    Args:
        path: The JSON file to write.
        document: The validated document to serialize.
    """
    with path.open("w", encoding="utf-8") as file:
        json.dump(document.model_dump(mode="json"), file, indent=4)
    logger.debug("Wrote document", path=path.name, fires=len(document.fires))


def read_document[Document: pydantic.BaseModel](
    path: pathlib.Path,
    model: type[Document],
) -> Document:
    """Return the document *path* holds, validated by *model*.

    Args:
        path: The JSON file to read.
        model: The model that validates the file's contents.

    Returns:
        The validated document.
    """
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def write_fire_scores_ccdf(
    path: pathlib.Path,
    document: peri_scribe.models.FireScores,
) -> None:
    """Write *document*'s scores to *path* as an HTML page with an inline SVG chart.

    Args:
        path: The HTML file to write.
        document: The validated fire scores to plot.
    """
    path.write_text(ccdf_html(document), encoding="utf-8")
    logger.debug("Wrote fire scores ccdf", path=path.name)
