"""Feed classes, their registry, and watermark observation for peri_scribe."""

from __future__ import annotations

import dataclasses
import json
import time
import typing
import urllib.parse

import requests
import structlog


logger = structlog.get_logger()

REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "peri_scribe-watcher/0.1"


@typing.runtime_checkable
class Feed(typing.Protocol):
    """Minimal interface for a feed that provides layer data.

    Concrete feed classes satisfy this protocol and are looked up through the
    :class:`FeedTypes` registry at runtime.
    """

    name: str
    url: str
    fire_name_column: str
    status_column: str
    fire_identifier_column: str | None
    complex_identifier_column: str | None
    complex_name_column: str | None
    is_complex_child_column: str | None

    @property
    def current_watermark(self) -> str | None:
        """The watermark currently observed for this feed's layer."""
        ...


RegisteredFeed = typing.TypeVar("RegisteredFeed", bound=type)


class FeedTypes:
    """Registry of feed classes, keyed by their class name.

    Feed classes are decorated with ``@FeedTypes.register`` at definition time.
    The ``feed_type`` string in the JSON configuration file is used to look up the
    corresponding class via :meth:`get_feed_class`.
    """

    registry: typing.ClassVar[dict[str, type]] = {}

    @classmethod
    def register(cls, feed_class: RegisteredFeed) -> RegisteredFeed:
        """Class decorator that registers *feed_class*.

        Args:
            feed_class: The feed class to register.

        Returns:
            The *feed_class* unchanged, so it can be stacked with other
            decorators.
        """
        cls.registry[feed_class.__name__] = feed_class
        return feed_class

    @classmethod
    def get_feed_class(cls, name: str) -> type:
        """Return the feed class registered under *name*.

        Args:
            name: The ``feed_type`` value from the JSON configuration (the feed
                class's ``__name__``).

        Returns:
            The registered class.
        """
        return cls.registry[name]


@FeedTypes.register
@dataclasses.dataclass(frozen=True, kw_only=True)
class ArcGISFeed:
    url: str
    fire_name_column: str
    status_column: str
    fire_identifier_column: str | None = None
    complex_identifier_column: str | None = None
    complex_name_column: str | None = None
    is_complex_child_column: str | None = None

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
    def current_watermark(self) -> str | None:
        """Observe and return a watermark for this feed's layer.

        The watermark is sorted JSON of the layer's ``Last-Modified`` and ``ETag``
        response headers and its feature count, keyed ``mtime``, ``etag``, and
        ``count``, so a plain string comparison detects any change.

        Returns:
            The observed watermark, or None when an observation fails.
        """
        parameters = {"f": "json", "_cb": time.time_ns()}
        try:
            response = requests.head(
                self.url,
                params=parameters,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as error:
            logger.warning(
                "Watermark check failed",
                url=self.url,
                error=str(error),
            )
            return None

        query_url = f"{self.url}/query"
        count_parameters = {"where": "1=1", "returnCountOnly": "true", "f": "json"}
        try:
            count_response = requests.get(
                query_url,
                params=count_parameters,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            count_response.raise_for_status()
            payload = count_response.json()
        except (requests.exceptions.RequestException, ValueError) as error:
            logger.warning(
                "Count query failed",
                url=query_url,
                error=str(error),
            )
            return None
        if not isinstance(payload, dict) or "count" not in payload:
            logger.warning(
                "Count query returned no count",
                url=query_url,
                response=payload,
            )
            return None

        return json.dumps(
            {
                "mtime": response.headers.get("Last-Modified"),
                "etag": response.headers.get("ETag"),
                "count": payload["count"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
