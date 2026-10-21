"""Construct distinct real inventory files without persistent application state."""

import pathlib


def inventory(directory: pathlib.Path, count: int = 6) -> tuple[pathlib.Path, ...]:
    """Give every source distinguishable complete bytes and deterministic ordering.

    Args:
        directory: Isolated fixture directory.
        count: Number of independent temporary sources.

    Returns:
        Ordered paths whose content identities can be checked independently.
    """
    result = tuple(directory / f"snapshot-{index}" for index in range(count))
    for index, path in enumerate(result):
        path.write_bytes(f"source bytes {index}".encode())
    return result
