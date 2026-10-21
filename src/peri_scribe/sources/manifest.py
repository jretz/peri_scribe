"""Compose ordered authenticated source leaves through reusable Merkle branches.

Design and verification:
[Source-index preparation](../../../docs/algorithms/source-index-preparation.md).
"""

from __future__ import annotations

import collections.abc
import hashlib
import itertools
import json

import peri_scribe.sources.digests
import spatial_data.product_cache


NAMESPACE = "source-merkle-manifest-v1"
ROOT_NAMESPACE = "source-merkle-root-v1"
DIGEST_HEX_LENGTH = hashlib.sha256().digest_size * 2
BRANCH_FIELD_COUNT = 3
type Branches = dict[tuple[str, str], str]


def framed(value: str) -> bytes:
    """Keep path and checksum fields unambiguous even with embedded separators.

    Args:
        value: Relative source path or opaque content identity.

    Returns:
        Terminated UTF-8 bytes with each literal zero escaped.
    """
    return peri_scribe.sources.digests.framed_value(value.encode())


def leaf(path: str, checksum: str) -> str:
    """Distinguish source leaves from internal nodes and the empty inventory.

    Args:
        path: Relative snapshot path, preserving its original inventory order.
        checksum: Freshly authenticated source content identity.

    Returns:
        The complete framed leaf's SHA-256 identity.
    """
    return hashlib.sha256(b"\x00" + framed(path) + framed(checksum)).hexdigest()


def valid_digest(value: object) -> bool:
    """Reject malformed cached branches before they can participate in composition.

    Args:
        value: Untrusted decoded manifest field.

    Returns:
        Whether the field is a canonical SHA-256 hexadecimal string.
    """
    return (
        isinstance(value, str)
        and len(value) == DIGEST_HEX_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def cached_branches() -> Branches:
    """Treat absent, damaged or incompatible manifests as disposable cache misses.

    Returns:
        Previously completed exact child-to-parent identities.
    """
    payload = spatial_data.product_cache.get(NAMESPACE, "current")
    if payload is None:
        return {}
    try:
        document = json.loads(payload)
    except ValueError:
        return {}
    if not isinstance(document, list):
        return {}
    result: Branches = {}
    for item in document:
        if (
            not isinstance(item, list)
            or len(item) != BRANCH_FIELD_COUNT
            or not all(valid_digest(value) for value in item)
        ):
            return {}
        left, right, parent = item
        if (left, right) in result:
            return {}
        result[left, right] = parent
    return result


def inventory_key(sources: collections.abc.Iterable[tuple[str, str]]) -> str:
    """Bind a completed root to every ordered path and authenticated content field.

    Args:
        sources: Ordered source pairs, with exactly two UTF-8 fields per occurrence.

    Returns:
        The SHA-256 identity of the complete prefix-free input encoding.
    """
    return peri_scribe.sources.digests.digest_fields(
        value.encode() for pair in sources for value in pair
    ).hex()


def cached_root(key: str) -> str | None:
    """Accept only canonical completed root receipts for the exact input identity.

    Args:
        key: The complete ordered source inventory identity.

    Returns:
        Its completed root, or None for absent, damaged, or incompatible products.
    """
    payload = spatial_data.product_cache.get(ROOT_NAMESPACE, key)
    if payload is None:
        return None
    try:
        value = payload.decode("ascii")
    except UnicodeDecodeError:
        return None
    return value if valid_digest(value) else None


def compose_root(sources: collections.abc.Iterable[tuple[str, str]]) -> str:
    """Calculate a root while reusing branches with exact matching child identities.

    Args:
        sources: Ordered relative paths and freshly authenticated source identities.

    Returns:
        A domain-separated Merkle root for the complete ordered source inventory.
    """
    level = list(itertools.starmap(leaf, sources))
    if not level:
        return hashlib.sha256(b"\x02").hexdigest()
    previous = cached_branches()
    current: Branches = {}
    while len(level) > 1:
        following: list[str] = []
        for index in range(0, len(level), 2):
            left = level[index]
            if index + 1 == len(level):
                following.append(left)
                continue
            right = level[index + 1]
            key = left, right
            parent = previous.get(key)
            if parent is None:
                parent = hashlib.sha256(
                    b"\x01" + bytes.fromhex(left) + bytes.fromhex(right),
                ).hexdigest()
            current[key] = parent
            following.append(parent)
        level = following
    spatial_data.product_cache.put(
        NAMESPACE,
        "current",
        json.dumps([(*key, value) for key, value in current.items()]).encode(),
    )
    return level[0]


def root(sources: collections.abc.Iterable[tuple[str, str]]) -> str:
    """Reuse a completed root before decoding unchanged branch receipts.

    Args:
        sources: Ordered relative paths and freshly authenticated source identities.

    Returns:
        A domain-separated Merkle root for the complete ordered source inventory.
    """
    if not spatial_data.product_cache.active():
        return compose_root(sources)
    entries = tuple(sources)
    key = inventory_key(entries)
    completed = cached_root(key)
    if completed is not None:
        return completed
    result = compose_root(entries)
    spatial_data.product_cache.put(ROOT_NAMESPACE, key, result.encode("ascii"))
    spatial_data.product_cache.prune(ROOT_NAMESPACE, {key})
    return result
