"""Compare raw-snapshot filesystem visibility with checked publication states."""

import dataclasses
import pathlib
import typing

import pytest

import peri_scribe.sources.feed_types
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import spatial_data.layers
import tests.helpers.doubles.peri_scribe.sources.fetching
import tests.helpers.doubles.peri_scribe.sources.snapshot_fetching


TOTAL_CHUNKS = 3


@dataclasses.dataclass(kw_only=True)
class SnapshotWriter:
    """Observe discoverable files at every prefix of an interrupted serialization."""

    directory: pathlib.Path
    states: list[dict[str, str]]
    prior: int
    fail_after: int | None
    original: typing.Callable[[pathlib.Path, list[spatial_data.layers.LayerData]], None]

    def write(
        self,
        path: pathlib.Path,
        layers: list[spatial_data.layers.LayerData],
    ) -> None:
        """Keep incomplete GeoPackages outside the model's discoverable file sequence.

        Args:
            path: Production-selected staging destination.
            layers: Complete input to the underlying GeoPackage serializer.

        Raises:
            Interrupted: At the selected staging prefix.
        """
        for count in range(TOTAL_CHUNKS + 1):
            state = next(
                state
                for state in self.states
                if state["phase"] == '"write"' and state["staged"] == str(count)
            )
            discovered = peri_scribe.sources.snapshots.existing_source_files(
                self.directory,
            )
            assert len(discovered) == state["files"].count("3") == self.prior
            if count == TOTAL_CHUNKS:
                self.original(path, layers)
            else:
                path.write_bytes(b"incomplete" * count)
            if count == self.fail_after:
                raise (
                    tests.helpers.doubles.peri_scribe.sources.snapshot_fetching
                ).Interrupted


def replay(states: list[dict[str, str]], directory: pathlib.Path) -> None:
    """Exercise skips, append-only full fetches, every interrupted prefix, and retry.

    Args:
        states: Complete TLC graph for three staged chunks and up to one prior file.
        directory: Isolated storage root for the implementation executions.
    """
    scenarios = {
        (int(state["prior"]), state["matching"] == "TRUE", state["full"] == "TRUE")
        for state in states
    }
    expected_scenarios = 6
    assert len(scenarios) == expected_scenarios
    for scenario, (prior, matching, full) in enumerate(sorted(scenarios)):
        checked = [
            state
            for state in states
            if int(state["prior"]) == prior
            and (state["matching"] == "TRUE") == matching
            and (state["full"] == "TRUE") == full
        ]
        for fail_after in (*range(TOTAL_CHUNKS + 1), None):
            replay_case(
                checked,
                directory / str(scenario) / str(fail_after),
                prior=prior,
                matching=matching,
                full=full,
                fail_after=fail_after,
            )


def replay_case(
    checked: list[dict[str, str]],
    base: pathlib.Path,
    *,
    prior: int,
    matching: bool,
    full: bool,
    fail_after: int | None,
) -> None:
    """Match one initialization and interruption boundary against production.

    Args:
        checked: The graph restricted to this initialization.
        base: Isolated application root.
        prior: Number of existing snapshots.
        matching: Whether the original timestamp equals the service marker.
        full: Whether to bypass the metadata shortcut.
        fail_after: Staged prefix to interrupt, or None for an uninterrupted write.
    """
    with pytest.MonkeyPatch.context() as patch:
        dataframe = (
            tests.helpers.doubles.peri_scribe.sources.snapshot_fetching
        ).configure_fetch(patch)
        feed = typing.cast(
            "peri_scribe.sources.feed_types.Feed",
            tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub(),
        )
        source_directory = peri_scribe.sources.snapshots.source_directory_path(
            base,
            2026,
            feed.name,
        )
        previous = (
            source_directory
            / peri_scribe.sources.snapshots.SourceFile(
                serial_number=0,
                last_edit_timestamp=2 if matching else 1,
            ).relative_path
        )
        if prior:
            previous.parent.mkdir(parents=True)
            previous.write_bytes(b"previous complete snapshot")
        writer = SnapshotWriter(
            directory=source_directory,
            states=checked,
            prior=prior,
            fail_after=fail_after,
            original=spatial_data.layers.write_geopackage,
        )
        with patch.context() as writing:
            writing.setattr(spatial_data.layers, "write_geopackage", writer.write)
            if fail_after is not None and (full or not matching):
                with pytest.raises(
                    tests.helpers.doubles.peri_scribe.sources.snapshot_fetching.Interrupted,
                ):
                    peri_scribe.sources.fetching.fetch_feed_snapshot(
                        feed,
                        base_dir=base,
                        year=2026,
                        full=full,
                    )
                assert (
                    len(
                        peri_scribe.sources.snapshots.existing_source_files(
                            source_directory,
                        ),
                    )
                    == prior
                )
        outcome = peri_scribe.sources.fetching.fetch_feed_snapshot(
            feed,
            base_dir=base,
            year=2026,
            full=full,
        )
        terminal = next(state for state in checked if state["phase"] == '"done"')
        assert len(
            peri_scribe.sources.snapshots.existing_source_files(source_directory),
        ) == terminal["files"].count("3")
        assert outcome.changed == (full or not matching)
        if outcome.changed:
            assert outcome.path is not None
            actual = spatial_data.layers.read_layer(outcome.path, feed.name)
            assert list(actual["name"]) == list(dataframe["name"])
            assert actual.geometry.equals(dataframe.geometry)
        if prior:
            assert previous.read_bytes() == b"previous complete snapshot"


def orphan_is_invisible(directory: pathlib.Path) -> None:
    """Hard termination may leave a staging directory without Python cleanup.

    Args:
        directory: An isolated source tree where recursive discovery actually runs.
    """
    orphan = directory / "000___" / "abandoned" / "snapshot.gpkg"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"partial")
    assert peri_scribe.sources.snapshots.existing_source_files(directory) == []
    assert (
        peri_scribe.sources.snapshots.snapshot_path_for_last_edit_timestamp(
            directory,
            2,
        )
        is None
    )
