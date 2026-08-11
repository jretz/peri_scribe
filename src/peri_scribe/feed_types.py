"""Feed classes and their registry for peri_scribe."""

from __future__ import annotations

import dataclasses
import typing
import urllib.parse


@typing.runtime_checkable
class Feed(typing.Protocol):
    """Minimal interface for a feed that provides layer data.

    Concrete feed classes satisfy this protocol and are looked up through the
    :class:`FeedTypes` registry at runtime.
    """

    name: str
    url: str


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
