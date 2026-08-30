"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import pathlib

import peri_scribe.fires.score_files


def test_fire_scores_path_names_output() -> None:
    assert peri_scribe.fires.score_files.fire_scores_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/fire_scores.json")


def test_fire_scores_ccdf_path_names_output() -> None:
    assert peri_scribe.fires.score_files.fire_scores_ccdf_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/fire_scores_ccdf.png")


def test_load_fire_scores_returns_none_when_scores_are_missing(
    tmp_path: pathlib.Path,
) -> None:
    assert peri_scribe.fires.score_files.load_fire_scores(tmp_path) is None
