"""HTTP request settings shared by every source fetcher.

They live in their own module because both the low-level feed metadata reader and the
download machinery need them, and the download machinery reaches the feed reader through
its imports.
"""

from __future__ import annotations

import contextlib
import typing

import requests

import peri_scribe.exceptions


# How long a request may wait for a response before it is abandoned. Archive downloads
# transfer many megabytes, so this is generous enough to cover them as well.
REQUEST_TIMEOUT_SECONDS = 60


# The number of response bytes read at a time while streaming a download.
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


@contextlib.contextmanager
def downloaded_response(
    url: str,
    *,
    stream: bool,
) -> typing.Generator[requests.Response]:
    """Yield the open response for *url*, translating download failures.

    The response is yielded inside the guard, so a transfer that fails part-way through
    its body is reported the same way as one that never connected.

    Args:
        url: The URL to download.
        stream: Whether to stream the body rather than reading it eagerly.

    Yields:
        The open response.

    Raises:
        ExternalDataError: If the download fails.
    """
    try:
        with requests.get(
            url,
            stream=stream,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            response.raise_for_status()
            yield response
    except requests.exceptions.RequestException as error:
        message = f"Failed to download {url}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
