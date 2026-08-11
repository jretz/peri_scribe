"""Retry utilities for peri_scribe — rate-limit detection and exponential backoff."""

from __future__ import annotations

import re

import structlog


logger = structlog.get_logger()

# Matches ArcGIS REST API rate-limit errors and captures the server-suggested
# retry-after seconds. The error body is a dict with an ``error`` key whose
# ``code`` is 429 and ``details`` list includes a "Retry after N sec" hint.
RATE_LIMIT_ERROR_PATTERN = re.compile(
    r"""(?x)
    ['\"]code['\"]\s*:\s*429
    .*
    Retry[ ]after[ ](\d+)[ ]sec
""",
)

# Matches any ArcGIS REST API error that carries a 429 code (loose fallback when
# the Retry-after hint cannot be parsed).
LOOSE_429_PATTERN = re.compile(r"""['\"]code['\"]\s*:\s*429""")

DEFAULT_MAX_RETRIES = 3
FALLBACK_RETRY_SECONDS = 60

# Base and cap for exponential backoff on transient network errors.
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAXIMUM_SECONDS = 30.0

# Compiled patterns matching exception strings for transient network or protocol
# failures that are worth retrying.
TRANSIENT_ERROR_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"IncompleteRead",
        r"Connection[ ]broken",
        r"Connection[ ]reset",
        r"Connection[ ]aborted",
        r"RemoteDisconnected",
        r"ChunkedEncodingError",
        r"ProtocolError",
        r"Read[ ]?Timeout",
        r"Connect[ ]?Timeout",
    ]
]


def rate_limit_retry_seconds(error: Exception) -> int | None:
    """Return the delay before retrying after a rate-limit error.

    Args:
        error: The exception raised by the ArcGIS query.

    Returns:
        The server-suggested retry-after seconds, the fallback delay when the
        error is a 429 response without a retry-after hint, or None when the
        error is not a rate-limit response.
    """
    error_string = str(error)
    rate_limit_match = RATE_LIMIT_ERROR_PATTERN.search(error_string)
    if rate_limit_match is not None:
        return int(rate_limit_match.group(1))
    if LOOSE_429_PATTERN.search(error_string) is not None:
        return FALLBACK_RETRY_SECONDS
    return None


def is_transient_error(error: Exception) -> bool:
    """Return True when *error* is likely a transient network failure.

    Returns:
        True when the error string matches a known transient-error pattern.
    """
    error_string = str(error)
    return any(pattern.search(error_string) for pattern in TRANSIENT_ERROR_PATTERNS)


def compute_backoff(
    attempt: int,
    *,
    base: float = BACKOFF_BASE_SECONDS,
    maximum: float = BACKOFF_MAXIMUM_SECONDS,
) -> float:
    """Return the exponential backoff delay for retry *attempt* (1-based).

    Returns:
        The delay in seconds, equal to ``min(base * 2**(attempt-1), maximum)``.
    """
    return min(base * (2 ** (attempt - 1)), maximum)
