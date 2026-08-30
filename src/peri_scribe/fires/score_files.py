"""Reading and writing the fire-scores output files."""

from __future__ import annotations

import pathlib

import peri_scribe.fires.files
import peri_scribe.models


SCORE_OUTPUT_FILENAME = "fire_scores.json"


CCDF_OUTPUT_FILENAME = "fire_scores_ccdf.png"


def fire_scores_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the fire-scores JSON for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The fire-scores output path.
    """
    return (
        year_directory
        / peri_scribe.fires.files.DERIVED_DIRECTORY_NAME
        / SCORE_OUTPUT_FILENAME
    )


def load_fire_scores(
    year_directory: pathlib.Path,
) -> peri_scribe.models.FireScores | None:
    """Return the saved fire scores for *year_directory*, when available.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The validated fire scores, or None when scoring has not been run yet.
    """
    path = fire_scores_path(year_directory)
    if not path.is_file():
        return None
    return peri_scribe.models.FireScores.model_validate_json(
        path.read_text(encoding="utf-8"),
    )


def fire_scores_ccdf_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the fire-scores CCDF for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The fire-scores CCDF output path.
    """
    return (
        year_directory
        / peri_scribe.fires.files.DERIVED_DIRECTORY_NAME
        / CCDF_OUTPUT_FILENAME
    )
