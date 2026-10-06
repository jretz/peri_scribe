"""TLC publication states constrain real snapshot discovery and retry."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.snapshot_publication


def test_fetch_feed_snapshot_matches_checked_publication_states(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "SnapshotPublication",
        "SnapshotPublication",
        tmp_path / "model",
    )
    tests.formal.helpers.snapshot_publication.replay(states, tmp_path / "snapshots")
    tests.formal.helpers.snapshot_publication.orphan_is_invisible(tmp_path / "orphan")
