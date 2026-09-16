"""Replace external source dependencies with controlled test doubles."""

from __future__ import annotations

import typing


class FakeResponse:
    """Stand-in for a requests response with a fixed body."""

    def __init__(self, body: bytes) -> None:
        """Initialize an HTTP response with controlled content.

        Args:
            body: HTTP response content in bytes.
        """
        self.body = body

    def raise_for_status(self) -> None:
        """No-op; the response is treated as successful."""

    @property
    def text(self) -> str:
        """The response body decoded as text.

        Returns:
            The response bytes decoded as UTF-8 text.
        """
        return self.body.decode("utf-8")

    def iter_content(self, chunk_size: int) -> typing.Iterator[bytes]:
        """Yield the body in chunks of *chunk_size* bytes.

        Args:
            chunk_size: The number of bytes per chunk.

        Yields:
            The body chunks.
        """
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]
