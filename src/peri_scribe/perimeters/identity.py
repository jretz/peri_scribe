"""Mapping identity shared by publication checkpoints and historical analysis."""

import datetime
import hashlib

import shapely


def signature(geometry: shapely.Geometry, observed: datetime.datetime | None) -> str:
    """Recognize a new survey or shape while ignoring polygon ring order.

    Args:
        geometry: The cleaned, nonempty published footprint.
        observed: Its survey time, if known.

    Returns:
        A stable digest of normalized geometry and the UTC observation time.
    """
    digest = hashlib.sha256(shapely.normalize(geometry).wkb)
    if observed is not None:
        digest.update(observed.astimezone(datetime.UTC).isoformat().encode())
    return digest.hexdigest()
