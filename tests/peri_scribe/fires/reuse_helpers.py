"""Provide data builders and stand-ins for reuse tests."""

import pathlib
import typing

import hypothesis.strategies
import shapely

import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.models
import tests.factories


@hypothesis.strategies.composite
def history_layers(
    draw: hypothesis.strategies.DrawFn,
) -> list[peri_scribe.models.LayerData]:
    """Interleave cached fires across layers with missing geometry and empty histories.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Small history layers with repeated fire keys and distinct row contents.
    """
    coordinates = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(-179, 179),
            hypothesis.strategies.integers(-80, 80),
        ),
    )
    layers = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.sampled_from(["perimeters", "points", "incidents"]),
            hypothesis.strategies.lists(
                hypothesis.strategies.tuples(
                    hypothesis.strategies.sampled_from(["first", "second", "third"]),
                    hypothesis.strategies.integers(0, 1000),
                    coordinates,
                ),
                max_size=8,
            ),
            min_size=1,
            max_size=3,
        ),
    )
    return [
        peri_scribe.models.LayerData(
            name=name,
            dataframe=tests.factories.geo_frame(
                {
                    "derivation_key": [key for key, _revision, _point in rows],
                    "revision": [revision for _key, revision, _point in rows],
                },
                [
                    None if point is None else shapely.Point(point)
                    for _key, _revision, point in rows
                ],
            ),
        )
        for name, rows in layers.items()
    ]


def source_key(
    read: peri_scribe.fires.sources.ReadFireSources,
    context: str = "context",
) -> str:
    """Extract the first fire's reuse key for dependency invalidation assertions.

    Args:
        read: Source observations and provenance used to compute a reuse key.
        context: Derivation settings signature included in the reuse key.

    Returns:
        The first grouped fire's dependency key.
    """
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    return next(
        iter(
            peri_scribe.fires.reuse.fire_keys(
                read,
                groups,
                pathlib.Path("sources"),
                context,
            ).values(),
        ),
    )


def write_partial_output_and_fail(
    path: pathlib.Path,
    _layers: list[peri_scribe.models.LayerData],
) -> None:
    """Simulate an interrupted write that leaves incomplete output.

    Args:
        path: Path supplied to the intercepted file operation.
        _layers: Layer contents accepted for writer compatibility.

    Raises:
        RuntimeError: Always, after writing partial content.
    """
    path.write_bytes(b"partial")
    message = "interrupted"
    raise RuntimeError(message)


def make_interrupted_replacement(
    *,
    path: pathlib.Path,
    replace: typing.Callable[..., pathlib.Path],
) -> typing.Callable[..., pathlib.Path]:
    """Create a callback with controlled dependencies.

    Interrupt metadata publication after the data file has been replaced.

    Args:
        path: Snapshot or output path selected for the controlled failure.
        replace: Original file replacement operation used for permitted destinations.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def interrupted(source: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        """Interrupt metadata publication after the data file has been replaced.

        Args:
            source: Temporary file containing the replacement data or metadata.
            target: Destination path for the replacement operation.

        Returns:
            The destination of a successful file replacement.

        Raises:
            OSError: If the destination is the reuse-signature file.
        """
        if target == peri_scribe.fires.reuse.signature_path(path):
            message = "interrupted metadata publication"
            raise OSError(message)
        return replace(source, target)

    return interrupted
