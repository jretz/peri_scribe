"""Place monthly rotation between context discovery and its first file open."""

import collections.abc
import compression.zstd
import pathlib
import typing


def rotate_before_read(
    path: pathlib.Path,
    *,
    read_records: collections.abc.Callable[
        [pathlib.Path],
        typing.Iterator[dict[str, object]],
    ],
) -> typing.Iterator[dict[str, object]]:
    """Publish an archive while the reader still holds the discovered plain path.

    Args:
        path: The plain monthly log selected for context recovery.
        read_records: The production reader that will observe the completed rotation.

    Returns:
        The recovered records from the path's compressed replacement.
    """
    with compression.zstd.open(
        path.with_suffix(".jsonl.zst"),
        "wt",
        encoding="utf-8",
    ) as stream:
        stream.write(path.read_text(encoding="utf-8"))
    path.unlink()
    return read_records(path)
