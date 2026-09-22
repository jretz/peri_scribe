"""Errors at the boundary between streamed bytes and spatial records."""


class GeometryStreamError(ValueError):
    """A streamed archive cannot produce usable GeoJSON polygon records."""
