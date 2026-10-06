"""TLC's output visibility contract applies at actual filesystem boundaries."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.static_download


def test_completed_download_matches_checked_visibility_and_retry(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "StaticDownload",
        "StaticDownload",
        tmp_path / "model",
    )
    tests.formal.helpers.static_download.replay(states, tmp_path / "outputs")
