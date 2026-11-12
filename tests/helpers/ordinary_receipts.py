"""Validate native ordinary lane receipts without depending on runner ownership."""

import json
import pathlib


def read_receipt(
    path: pathlib.Path,
    digest: str,
    index: int,
    *,
    error_type: type[Exception] = ValueError,
) -> tuple[str, ...]:
    """Reject receipts not owned by this exact ordinary plan and lane.

    Args:
        path: The closed native collection or completion receipt.
        digest: Expected ordinary plan's SHA-256 content identity.
        index: Expected native lane index.
        error_type: The caller's exception class for incompatible receipt fields.

    Returns:
        The complete ordered native node IDs.
    """
    observed, owner, nodes = json.loads(path.read_bytes())
    if (
        observed != digest
        or owner != index
        or not isinstance(nodes, list)
        or not all(isinstance(nodeid, str) for nodeid in nodes)
    ):
        message = f"Invalid native pytest lane receipt {path}"
        raise error_type(message)
    return tuple(nodes)
