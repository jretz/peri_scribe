"""Compare actual lexical source memo traces with the proved generic memo definition."""

from __future__ import annotations

import itertools
import pathlib

import peri_scribe.sources.provenance
import tests.formal.helpers.oracle


def compare_traces(*, windows: bool) -> int:
    """Preserve roots, source spelling, order and duplicates in concrete memo histories.

    Args:
        windows: Whether equal Windows Path objects have different lexical spelling.

    Returns:
        The number of bounded ordered histories compared with executable Lean.
    """
    if windows:
        directories = (
            pathlib.PureWindowsPath("C:/sources"),
            pathlib.PureWindowsPath("c:/SOURCES/feed"),
        )
        paths = (
            pathlib.PureWindowsPath("C:/sources/feed/A.gpkg"),
            pathlib.PureWindowsPath("c:/SOURCES/FEED/a.gpkg"),
            pathlib.PureWindowsPath("C:/sources/feed/../fire.gpkg"),
        )
    else:
        directories = (pathlib.Path("/sources"), pathlib.Path("/sources/feed"))
        paths = (
            pathlib.Path("/sources/feed/fire.gpkg"),
            pathlib.Path("/sources/feed/火,\0.gpkg"),
            pathlib.Path("/sources/feed/../fire.gpkg"),
        )
    pairs = list(itertools.product(range(len(directories)), range(len(paths))))
    results = [str(paths[path].relative_to(directories[root])) for root, path in pairs]
    tokens = {value: position for position, value in enumerate(dict.fromkeys(results))}
    table = [tokens[value] for value in results]
    histories = [
        history
        for length in range(4)
        for history in itertools.product(range(len(pairs)), repeat=length)
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        [
            " ".join(["source-path", *map(str, table), "--", *map(str, history)])
            for history in histories
        ],
        executable="oraclePresentationFlow",
    )
    for history, values in zip(histories, expected, strict=True):
        owners = [
            peri_scribe.sources.provenance.SourcePaths(directory=directory)
            for directory in directories
        ]
        actual = tuple(
            tokens[owners[pairs[key][0]].relative(paths[pairs[key][1]])]
            for key in history
        )
        assert actual == values
    return len(histories)
