"""Build inputs for folders tests."""

from __future__ import annotations

import peri_scribe.kml.builder
import peri_scribe.kml.fire_data


def ring_style_urls_for(fire: peri_scribe.kml.fire_data.FireGeometry) -> dict[str, str]:
    """Return a ring style URL for every color *fire*'s rings use.

    The mapping mirrors the builder's, so the fire's rings resolve to the styles the KMZ
    document defines.

    Args:
        fire: The fire to symbolize.

    Returns:
        The ring style URLs.
    """
    return peri_scribe.kml.builder.ring_style_urls_for([fire])
