"""Feed classes and last-edit timestamp observation for peri_scribe."""

from __future__ import annotations

import time
import typing
import urllib.parse

import pydantic
import requests
import structlog

import peri_scribe.retry


logger = structlog.get_logger()

REQUEST_TIMEOUT_SECONDS = 30
PERI_SCRIBE_VERSION = "0.1"
USER_AGENT = f"peri_scribe-watcher/{PERI_SCRIBE_VERSION}"


def fetch_layer_metadata(url: str) -> object:
    """Fetch and parse the layer metadata for *url*.

    Args:
        url: The layer's REST endpoint URL.

    Returns:
        The parsed JSON metadata payload.
    """
    parameters = {"f": "json", "_cb": time.time_ns()}
    response = requests.get(
        url,
        params=parameters,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


@typing.runtime_checkable
class Feed(typing.Protocol):
    """Minimal interface for a feed that provides layer data.

    Concrete feed classes satisfy this protocol and are validated from the JSON
    configuration at runtime. All members are read-only, since a feed's configuration
    does not change after it is loaded.
    """

    @property
    def name(self) -> str:
        """The feed's name."""
        ...

    @property
    def url(self) -> str:
        """The feed's layer REST endpoint URL."""
        ...

    @property
    def fire_name_column(self) -> str:
        """The column holding each fire's name."""
        ...

    @property
    def status_column(self) -> str:
        """The column holding each fire's status."""
        ...

    @property
    def fire_identifier_columns(self) -> tuple[str, ...]:
        """The columns holding each fire's identifiers, primary first."""
        ...

    @property
    def mission_column(self) -> str | None:
        """The column holding each feature's mapping mission code, or None."""
        ...

    @property
    def observation_time_column(self) -> str | None:
        """The column holding each feature's observation time, or None."""
        ...

    @property
    def point_of_origin_state_column(self) -> str | None:
        """The column holding each feature's point of origin state, or None."""
        ...

    @property
    def point_of_origin_fips_column(self) -> str | None:
        """The column holding each feature's point of origin FIPS code, or None."""
        ...

    @property
    def complex_identifier_column(self) -> str | None:
        """The column holding each fire's complex identifier, or None."""
        ...

    @property
    def complex_name_column(self) -> str | None:
        """The column holding each fire's complex name, or None."""
        ...

    @property
    def is_complex_child_column(self) -> str | None:
        """The column marking complex children, or None."""
        ...

    @property
    def modified_column(self) -> str | None:
        """The column holding each feature's modified timestamp, or None."""
        ...

    @property
    def current_last_edit_timestamp(self) -> int | None:
        """The last-edit timestamp currently observed for this feed's layer."""
        ...


class ArcGISFeed(pydantic.BaseModel):
    """A validated ArcGIS feature layer feed."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    feed_type: typing.Literal["ArcGISFeed"] = "ArcGISFeed"
    url: str
    fire_name_column: str
    status_column: str
    fire_identifier_columns: tuple[str, ...] = ()
    mission_column: str | None = None
    observation_time_column: str | None = None
    point_of_origin_state_column: str | None = None
    point_of_origin_fips_column: str | None = None
    complex_identifier_column: str | None = None
    complex_name_column: str | None = None
    is_complex_child_column: str | None = None
    modified_column: str | None = None

    @property
    def path_segments(self) -> list[str]:
        return [
            segment
            for segment in urllib.parse.urlsplit(self.url).path.split("/")
            if segment
        ]

    @property
    def service_name(self) -> str:
        return self.path_segments[-3]

    @property
    def layer_id(self) -> int:
        return int(self.path_segments[-1])

    @property
    def name(self) -> str:
        return f"{self.service_name}_{self.layer_id}"

    @property
    def current_last_edit_timestamp(self) -> int | None:
        """Observe and return the last-edit timestamp for this feed's layer.

        The timestamp is the layer's ``editingInfo.lastEditDate`` value, in epoch
        milliseconds. The server only updates that timestamp when the data is actually
        edited. Transient network failures and rate-limit responses are retried before
        giving up.

        Returns:
            The observed last-edit timestamp, or None when an observation fails.
        """
        try:
            payload = peri_scribe.retry.run_with_retry(
                self.name,
                lambda: fetch_layer_metadata(self.url),
            )
        except (requests.exceptions.RequestException, ValueError) as error:
            logger.warning(
                "Last-edit timestamp check failed",
                url=self.url,
                error=str(error),
            )
            return None
        if not isinstance(payload, dict):
            logger.warning(
                "Last-edit timestamp check failed",
                url=self.url,
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
                url=self.url,
                error="no editingInfo.lastEditDate",
            )
            return None
        return int(last_edit)
