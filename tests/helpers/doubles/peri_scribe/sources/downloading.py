"""Replace downloading dependencies with controlled test doubles."""

from __future__ import annotations

import typing

import requests

import peri_scribe.sources.external_sources
import tests.helpers.doubles.peri_scribe.sources.external_source


def make_failing_archive_responder(
    *,
    page: str,
) -> typing.Callable[
    ...,
    tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse,
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
    ) -> tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse:
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
            return (
                tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                    page.encode("utf-8"),
                )
            )
        message = "boom"
        raise requests.exceptions.RequestException(
            message,
        )

    return get
