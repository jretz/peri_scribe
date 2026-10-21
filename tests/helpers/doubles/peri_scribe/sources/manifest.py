"""Reject branch hydration when an exact completed root receipt is available."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import peri_scribe.sources.manifest


def reject_branch_read() -> peri_scribe.sources.manifest.Branches:
    """Make accidental warm-path branch parsing fail the focused regression.

    Raises:
        AssertionError: Whenever the completed root fast path reaches branch storage.
    """
    message = "A complete root receipt must avoid branch hydration"
    raise AssertionError(message)
