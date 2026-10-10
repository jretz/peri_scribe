"""Encode the viewer's small fire maps as lossless WebP data URLs.

[Preview rendering reasoning](../../docs/algorithms/preview-orientation.md)
explains the contract and correctness argument.
"""

from __future__ import annotations

import base64
import hashlib
import io

import PIL.Image

import peri_scribe.kml.fire_data
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.preview_geometry
import peri_scribe.presentation.preview_palette
import spatial_data.cache_values
import spatial_data.product_cache


NAMESPACE = "perimeter-preview-webp-v1"
DATA_URL_PREFIX = "data:image/webp;base64,"


def encode_webp(image: PIL.Image.Image) -> bytes:
    """Use libwebp's maximum lossless compression effort without transport compression.

    Args:
        image: Quantized RGBA pixels, including antialiased transparency.

    Returns:
        Metadata-free WebP bytes that preserve every quantized pixel exactly.
    """
    stream = io.BytesIO()
    image.save(stream, format="WEBP", lossless=True, quality=100, method=6, exact=True)
    return stream.getvalue()


def cached_content(key: str) -> bytes | None:
    """Reject malformed disposable images before embedding them in a snapshot.

    Args:
        key: Fingerprint of every ordered geometry and color used to draw the map.

    Returns:
        A complete native-size lossless WebP, or None so it is rendered again.
    """
    content = spatial_data.product_cache.get(NAMESPACE, key)
    if content is None:
        return None
    try:
        with PIL.Image.open(io.BytesIO(content)) as image:
            image.load()
            valid = image.format == "WEBP" and image.size == (
                peri_scribe.presentation.preview_geometry.SIZE
            )
    except OSError, ValueError:
        return None
    return content if valid else None


def fire_preview(fire: peri_scribe.presentation.fire_data.FireSummary) -> str | None:
    """Draw each fire's latest state using the KMZ's shared ring-color selection.

    Args:
        fire: A prepared fire with full and differential perimeter histories.

    Returns:
        A browser-ready WebP data URL, or None for a fire without drawable perimeters.
    """
    perimeters = tuple(
        perimeter.geometry
        for perimeter in fire.perimeters
        if peri_scribe.presentation.preview_geometry.polygons(perimeter.geometry)
    )[-3:]
    if not perimeters:
        return None
    fills = tuple(
        (ring.geometry, color)
        for ring, color in peri_scribe.kml.fire_data.interior_ring_colors(
            fire.progression_rings,
            fire.perimeters,
        )
        if peri_scribe.presentation.preview_geometry.polygons(ring.geometry)
    )
    key = (
        hashlib.sha256(spatial_data.cache_values.dumps((fills, perimeters))).hexdigest()
        if spatial_data.product_cache.active()
        else None
    )
    content = cached_content(key) if key is not None else None
    if content is None:
        rendered = peri_scribe.presentation.preview_geometry.draw_map(fills, perimeters)
        quantized = peri_scribe.presentation.preview_palette.quantize(rendered)
        content = encode_webp(quantized.image)
        if key is not None:
            spatial_data.product_cache.put(NAMESPACE, key, content)
    return DATA_URL_PREFIX + base64.b64encode(content).decode("ascii")
