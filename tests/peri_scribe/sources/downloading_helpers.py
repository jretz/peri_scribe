"""Provide data builders and stand-ins for downloading tests."""

from __future__ import annotations

import typing

import requests

import peri_scribe.sources.external_sources
import tests.peri_scribe.sources.external_source_helpers


def make_failing_archive_responder(
    *,
    page: str,
) -> typing.Callable[
    ...,
    tests.peri_scribe.sources.external_source_helpers.FakeResponse,
]:
    """Create a callback with controlled dependencies.

    Serve the buildings index and fail the subsequent archive download.

    Args:
        page: Buildings index HTML served before archive requests.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def get(
        url: str,
        **kwargs: object,
    ) -> tests.peri_scribe.sources.external_source_helpers.FakeResponse:
        """Serve the buildings index and fail the subsequent archive download.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            kwargs: HTTP request options accepted by the response substitute.

        Returns:
            The buildings index response.

        Raises:
            requests.exceptions.RequestException: If the
                request targets an archive.
        """
        if url == peri_scribe.sources.external_sources.BUILDINGS_SOURCE.url:
            return tests.peri_scribe.sources.external_source_helpers.FakeResponse(
                page.encode("utf-8"),
            )
        message = "boom"
        raise requests.exceptions.RequestException(
            message,
        )

    return get
