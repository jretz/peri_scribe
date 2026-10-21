"""Describe ordered Merkle roots recursively without cached iterative levels."""

from __future__ import annotations

import hashlib
import typing


def root(sources: typing.Sequence[tuple[str, str]]) -> bytes:
    """Split at the largest complete left subtree before recursively composing.

    Args:
        sources: Ordered path and content fields, including repeated occurrences.

    Returns:
        The independently framed and hashed inventory root.
    """
    if not sources:
        return hashlib.sha256(b"\x02").digest()
    if len(sources) == 1:
        fields = (
            value.encode().replace(b"\x00", b"\x00\x01") + b"\x00\x00"
            for value in sources[0]
        )
        return hashlib.sha256(b"\x00" + b"".join(fields)).digest()
    split = 1 << ((len(sources) - 1).bit_length() - 1)
    return hashlib.sha256(
        b"\x01" + root(sources[:split]) + root(sources[split:]),
    ).digest()
