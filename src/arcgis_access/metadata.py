"""ArcGIS REST metadata requests and last-edit observations."""

from __future__ import annotations

import time

import requests
import structlog

import arcgis_access.retry


logger = structlog.get_logger()


def fetch_layer_metadata(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
) -> object:
    """Fetch and parse the layer metadata for *url*.

    Args:
        url: The layer's REST endpoint URL.
        user_agent: The caller identity sent with requests.
        timeout_seconds: Maximum request wait in seconds.

    Returns:
        The parsed JSON metadata payload.
    """
    parameters = {"f": "json", "_cb": time.time_ns()}
    response = requests.get(
        url,
        params=parameters,
        headers={"User-Agent": user_agent},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def observe_layer_last_edit_timestamp(
    url: str,
    name: str,
    *,
    user_agent: str,
    timeout_seconds: int,
) -> int | None:
    """Observe and return the layer's ``editingInfo.lastEditDate`` value.

    The timestamp is in epoch milliseconds. The server only updates it when the data is
    actually edited. Transient network failures and rate-limit responses are retried
    before giving up.

    Args:
        url: The layer's REST endpoint URL.
        user_agent: The caller identity sent with requests.
        timeout_seconds: Maximum request wait in seconds.
        name: Human-readable layer identifier for log messages.

    Returns:
        The observed last-edit timestamp, or None when an observation fails.
    """
    try:
        payload = arcgis_access.retry.run_with_retry(
            name,
            lambda: fetch_layer_metadata(
                url,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
            ),
        )
    except (requests.exceptions.RequestException, ValueError) as error:
        logger.warning(
            "Last-edit timestamp check failed",
            url=url,
            error=str(error),
            exc_info=True,
        )
        return None
    if not isinstance(payload, dict):
        logger.warning(
            "Last-edit timestamp check failed",
            url=url,
            error="unexpected response shape",
        )
        return None
    editing_info = payload.get("editingInfo")
    last_edit = (
        editing_info.get("lastEditDate") if isinstance(editing_info, dict) else None
    )
    if last_edit is None:
        logger.warning(
            "Last-edit timestamp check failed",
            url=url,
            error="no editingInfo.lastEditDate",
        )
        return None
    return int(last_edit)
