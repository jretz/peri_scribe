"""Generate builder examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies


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
