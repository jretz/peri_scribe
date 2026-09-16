"""Provide data builders and stand-ins for builder tests."""

from __future__ import annotations

import datetime
import pathlib
import typing

import hypothesis.strategies
import shapely.geometry

import peri_scribe.kml.descriptions
import peri_scribe.kml.fire_data
import peri_scribe.kml.perimeters
import peri_scribe.models
import tests.factories


if typing.TYPE_CHECKING:
    import geopandas


def archive_images() -> hypothesis.strategies.SearchStrategy[dict[str, bytes]]:
    """Exercise KMZ members with Unicode filenames and both compression policies.

    Returns:
        Relative image paths and opaque contents, without reserved document filenames.
    """
    stem = hypothesis.strategies.text(
        alphabet=hypothesis.strategies.characters(
            categories=("L", "N"),
            include_characters=" -_&'",
        ),
        min_size=1,
        max_size=24,
    )
    filename = hypothesis.strategies.tuples(
        stem,
        hypothesis.strategies.sampled_from([".png", ".PNG", ".jpg", ".svg", ".webp"]),
    ).map(lambda parts: f"plots/{parts[0]}{parts[1]}")
    return hypothesis.strategies.dictionaries(
        filename,
        hypothesis.strategies.binary(max_size=1024),
        max_size=6,
    )


def recording_archive_factory(
    archives: list[FakeArchive],
) -> typing.Callable[..., FakeArchive]:
    """Return a zipfile stand-in that records every archive it opens.

    Args:
        archives: The list each opened archive is appended to.

    Returns:
        The stand-in for ``zipfile.ZipFile``.
    """

    def fake_zipfile(*args: object, **kwargs: object) -> FakeArchive:
        """Capture archive construction and writes without creating a KMZ.

        Args:
            args: Positional archive constructor arguments.
            kwargs: Named archive constructor options.

        Returns:
            The recorded in-memory archive.
        """
        archive = FakeArchive(*args, **kwargs)
        archives.append(archive)
        return archive

    return fake_zipfile


class FakeArchive:
    """In-memory zip archive stand-in that records its writes."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Retain archive options so compression choices can be asserted.

        Args:
            args: Positional archive constructor arguments.
            kwargs: Named archive constructor options.
        """
        self.args = args
        self.kwargs = kwargs
        self.writes: list[tuple[str, str | bytes, int | None]] = []

    def __enter__(self) -> typing.Self:
        """Expose the in-memory archive to the writer context.

        Returns:
            This archive recorder.
        """
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc_value: object,
        _traceback: object,
    ) -> None:
        """Let writer exceptions propagate out of the archive context.

        Args:
            _exc_type: Unused exception type from the context.
            _exc_value: Unused exception instance from the context.
            _traceback: Unused traceback from the context.
        """
        return

    def writestr(
        self,
        name: str,
        data: str | bytes,
        compress_type: int | None = None,
    ) -> None:
        """Record archive contents and compression choices for assertions.

        Args:
            name: The member filename inside the KMZ.
            data: The member content supplied by the writer.
            compress_type: The optional per-member compression override.
        """
        self.writes.append((name, data, compress_type))


SCENARIO_TIME = datetime.datetime(2026, 8, 20, 12, 0, tzinfo=datetime.UTC)


def new_folder_scenario() -> tuple[
    list[peri_scribe.kml.fire_data.FireGeometry],
    peri_scribe.models.FireScores,
]:
    """Return one fire that qualifies for every new top-level folder.

    Returns:
        The fire and its score.
    """
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Alpha",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(0.0, 0.0),
        perimeters=(
            peri_scribe.kml.perimeters.Perimeter(
                geometry=tests.factories.square(0.02),
                observation_time=SCENARIO_TIME - datetime.timedelta(hours=48),
            ),
            peri_scribe.kml.perimeters.Perimeter(
                geometry=tests.factories.square(0.03),
                observation_time=SCENARIO_TIME,
            ),
        ),
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=SCENARIO_TIME - datetime.timedelta(days=1),
            observation_time=SCENARIO_TIME,
            total_personnel=50.0,
        ),
        type_one=True,
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Alpha",
                score=10,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
        ],
    )
    return [fire], scores


NEW_FOLDER_NAMES = [
    "New, Notable Fires",
    "Type 1 Fires",
    "Fast Growing Fires (acres)",
    "Fast Growing Fires (%)",
    "Fires with Most Personnel",
]


def make_history_layer_reader(
    *,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> typing.Callable[..., geopandas.GeoDataFrame]:
    """Create a callback to isolate derived-layer reads from persistent geography.

    Args:
        perimeters: Perimeter history returned for the perimeter layer.
        points: Point history returned for the point layer.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def read_layer(_path: pathlib.Path, layer_name: str) -> geopandas.GeoDataFrame:
        """Isolate derived-layer reads from persistent geography.

        Args:
            _path: The requested path, without reading its contents.
            layer_name: The requested history layer.

        Returns:
            The synthetic history frame used by this scenario.
        """
        return perimeters if layer_name == "perimeter_history" else points

    return read_layer


def make_interrupted_archive_writer(
    *,
    output: pathlib.Path,
    previous: bytes,
) -> typing.Callable[..., None]:
    """Create a callback to simulate a disk failure while the archive is incomplete.

    Args:
        output: Output path used by the controlled write or renderer.
        previous: Complete archive contents that must survive a failed replacement.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def fail_after_partial_write(
        path: pathlib.Path,
        _text: str,
        _images: object,
    ) -> None:
        """Simulate a disk failure while the archive is incomplete.

        Args:
            path: The temporary archive path where the partial write occurs.
            _text: The KML document accepted to match the writer's signature; unused.
            _images: The plot images accepted to match the writer's signature; unused.

        Raises:
            OSError: After the incomplete archive is written.
        """
        path.write_bytes(b"partial archive")
        assert output.read_bytes() == previous
        message = "disk failure"
        raise OSError(message)

    return fail_after_partial_write
