"""Connect every checked summary-selection outcome to authenticated product reads."""

import collections.abc
import pathlib
import re

import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.geo.source_summaries
import spatial_data.geometry_pool
import spatial_data.product_cache
import tests.formal.helpers.parsed_cache
import tests.helpers.factories.peri_scribe.geo.database
import tests.helpers.factories.peri_scribe.geo.source_summaries


CONFIGURATION_COUNT = 256
PATH_COUNT = 2
FUNCTION_FIELD_COUNT = 4


def pair(value: str) -> tuple[int, int]:
    """Decode a two-element numeric TLC function or its sequence rendering.

    Args:
        value: The complete checked function value exported by TLC.

    Returns:
        Its values for paths one and two, in that order.
    """
    values = tests.formal.helpers.parsed_cache.numbers(value)
    if len(values) == FUNCTION_FIELD_COUNT:
        assert values[::2] == (1, 2)
        return values[1], values[3]
    assert len(values) == PATH_COUNT
    return values[0], values[1]


def outcomes(
    states: collections.abc.Iterable[dict[str, str]],
) -> tuple[dict[str, str], ...]:
    """Retain every actual completed selection valuation from the checked graph.

    Args:
        states: All states exported by the successful SourceSummaries check.

    Returns:
        The complete current/previous/mode outcome matrix.
    """
    result = tuple(state for state in states if state["position"] == "3")
    assert len(result) == CONFIGURATION_COUNT
    return result


def source_contents(path: pathlib.Path) -> peri_scribe.geo.package.GeopackageContents:
    """Give each checked source revision a complete independently decoded parse.

    Args:
        path: Concrete authoritative source bytes for one checked revision.

    Returns:
        Ordered rows and memberships belonging to that exact revision.
    """
    return tests.helpers.factories.peri_scribe.geo.database.contents(
        int(path.read_text(encoding="utf-8")),
    )


def replay(state: dict[str, str], directory: pathlib.Path) -> None:
    """Match summary hits and actual hydrated misses to one checked final selection.

    Args:
        state: One checked complete SourceSummaries outcome.
        directory: Private source files and transactional product cache for this case.
    """
    source_root = directory / "sources"
    current = pair(state["current"])
    previous = pair(state["previous"])
    modes = re.findall(r'"([^\"]+)"', state["modes"])
    assert len(modes) == PATH_COUNT
    paths: list[pathlib.Path] = []
    cache = directory / "products.sqlite"
    for serial, (revision, mode) in enumerate(zip(previous, modes, strict=True), 1):
        path = tests.helpers.factories.peri_scribe.geo.source_summaries.snapshot(
            source_root,
            serial,
            revision,
        )
        paths.append(path)
        if mode == "absent":
            continue
        with spatial_data.product_cache.scope(
            cache,
            "old" if mode == "old-context" else "current",
        ):
            peri_scribe.geo.source_summaries.seed_summaries(
                source_root,
                {path: source_contents(path)},
                {path: peri_scribe.geo.database.snapshot_checksum(path)},
            )
            if mode == "damaged":
                spatial_data.product_cache.put(
                    peri_scribe.geo.source_summaries.NAMESPACE,
                    peri_scribe.geo.source_summaries.snapshot_key(
                        path,
                        source_root,
                        peri_scribe.geo.database.snapshot_checksum(path),
                    ),
                    b"invalid summary",
                )
    for path, revision in zip(paths, current, strict=True):
        path.write_text(str(revision), encoding="utf-8")
    with spatial_data.product_cache.scope(cache, "current"):
        summaries, hydrated = peri_scribe.geo.source_summaries.read_summaries(
            paths,
            source_root,
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )
        expected_hydrated = {
            paths[position - 1]
            for position in tests.formal.helpers.parsed_cache.numbers(state["hydrated"])
        }
        assert set(hydrated) == expected_hydrated
        assert list(summaries) == paths
        assert summaries == {
            path: peri_scribe.geo.source_summaries.summarize(
                path,
                source_contents(path),
            )
            for path in paths
        }
