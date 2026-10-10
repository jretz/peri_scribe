"""Control HTTP outcomes without changing real city conversion or persistence."""

from __future__ import annotations

import dataclasses
import io
import typing

import requests


if typing.TYPE_CHECKING:
    import pytest


def response(
    content: bytes = b"",
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    """Supply requests' own status and context-manager behavior around fixed bytes.

    Args:
        content: The complete response body.
        status: The HTTP response status.
        headers: Provider validators returned with the body.

    Returns:
        An in-memory response with no network-backed connection.
    """
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers or {})
    result.raw = io.BytesIO(content)
    return result


@dataclasses.dataclass(kw_only=True)
class Responder:
    """Record conditional requests while consuming prescribed HTTP outcomes."""

    outcomes: list[requests.Response | Exception]
    calls: list[tuple[str, dict[str, str], float]] = dataclasses.field(
        default_factory=list,
    )

    def __call__(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> requests.Response:
        """Return the next prescribed outcome and preserve the outgoing validators.

        Args:
            url: The source URL requested by the fetcher.
            headers: Conditional HTTP headers chosen from usable cached metadata.
            timeout: The shared request timeout.

        Returns:
            The next controlled response.

        """
        self.calls.append((url, headers, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def install(
    monkeypatch: pytest.MonkeyPatch,
    *outcomes: requests.Response | Exception,
) -> Responder:
    """Replace only HTTP transport so persistence remains real in source tests.

    Args:
        monkeypatch: The per-test dependency replacement owner.
        outcomes: Responses or exceptions returned by successive requests.

    Returns:
        The callable recorder for assertions about request headers and frequency.
    """
    responder = Responder(outcomes=list(outcomes))
    monkeypatch.setattr(requests, "get", responder)
    return responder
