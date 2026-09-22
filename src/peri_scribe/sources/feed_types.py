"""Feed classes and last-edit timestamp observation for peri_scribe."""

from __future__ import annotations

import typing
import urllib.parse

import pydantic

import arcgis_access.metadata
import peri_scribe.sources.network


PERI_SCRIBE_VERSION = "0.1"
USER_AGENT = f"peri_scribe-watcher/{PERI_SCRIBE_VERSION}"


@typing.runtime_checkable
class Feed(typing.Protocol):
    """Minimal interface for a feed that provides layer data.

    Concrete feed classes satisfy this protocol and are validated from the JSON
    configuration at runtime. All members are read-only, since a feed's configuration
    does not change after it is loaded.
    """

    @property
    def name(self) -> str:
        """The feed's name.

        Returns:
            The feed's name.
        """
        ...

    @property
    def url(self) -> str:
        """The feed's layer REST endpoint URL.

        Returns:
            The feed's layer REST endpoint URL.
        """
        ...

    @property
    def fire_name_column(self) -> str:
        """The column holding each fire's name.

        Returns:
            The column holding each fire's name.
        """
        ...

    @property
    def status_column(self) -> str:
        """The column holding each fire's status.

        Returns:
            The column holding each fire's status.
        """
        ...

    @property
    def fire_identifier_columns(self) -> tuple[str, ...]:
        """The columns holding each fire's identifiers, primary first.

        Returns:
            The columns holding each fire's identifiers, primary first.
        """
        ...

    @property
    def mission_column(self) -> str | None:
        """The column holding each feature's mapping mission code, or None.

        Returns:
            The column holding each feature's mapping mission code, or None.
        """
        ...

    @property
    def observation_time_column(self) -> str | None:
        """The column holding each feature's observation time, or None.

        Returns:
            The column holding each feature's observation time, or None.
        """
        ...

    @property
    def point_of_origin_state_column(self) -> str | None:
        """The column holding each feature's point of origin state, or None.

        Returns:
            The column holding each feature's point of origin state, or None.
        """
        ...

    @property
    def point_of_origin_fips_column(self) -> str | None:
        """The column holding each feature's point of origin FIPS code, or None.

        Returns:
            The column holding each feature's point of origin FIPS code, or None.
        """
        ...

    @property
    def complex_identifier_column(self) -> str | None:
        """The column holding each fire's complex identifier, or None.

        Returns:
            The column holding each fire's complex identifier, or None.
        """
        ...

    @property
    def complex_name_column(self) -> str | None:
        """The column holding each fire's complex name, or None.

        Returns:
            The column holding each fire's complex name, or None.
        """
        ...

    @property
    def is_complex_child_column(self) -> str | None:
        """The column marking complex children, or None.

        Returns:
            The column marking complex children, or None.
        """
        ...

    @property
    def change_columns(self) -> tuple[str, ...]:
        """The timestamp columns that change when a feature is edited.

        Returns:
            The timestamp columns that change when a feature is edited.
        """
        ...

    @property
    def current_last_edit_timestamp(self) -> int | None:
        """The last-edit timestamp currently observed for this feed's layer.

        Returns:
            The last-edit timestamp currently observed for this feed's layer.
        """
        ...


class ArcGISFeed(pydantic.BaseModel):
    """A validated ArcGIS feature layer feed."""

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
    change_columns: tuple[str, ...] = ()

    @property
    def path_segments(self) -> list[str]:
        """The nonempty URL path segments identifying the ArcGIS layer.

        Returns:
            The service path components, with empty segments omitted.
        """
        return [
            segment
            for segment in urllib.parse.urlsplit(self.url).path.split("/")
            if segment
        ]

    @property
    def service_name(self) -> str:
        """The ArcGIS service name used to identify the feed.

        Returns:
            The service component of the layer URL.
        """
        return self.path_segments[-3]

    @property
    def layer_id(self) -> int:
        """The numeric layer identifier within the ArcGIS service.

        Returns:
            The layer number from the final URL segment.
        """
        return int(self.path_segments[-1])

    @property
    def name(self) -> str:
        """The service and layer name used for stored snapshots.

        Returns:
            The service name and layer number joined with an underscore.
        """
        return f"{self.service_name}_{self.layer_id}"

    @property
    def current_last_edit_timestamp(self) -> int | None:
        """The last-edit timestamp currently observed for this feed's layer.

        Returns:
            The observed last-edit timestamp, or None when an observation fails.
        """
        return arcgis_access.metadata.observe_layer_last_edit_timestamp(
            self.url,
            self.name,
            user_agent=USER_AGENT,
            timeout_seconds=peri_scribe.sources.network.REQUEST_TIMEOUT_SECONDS,
        )
