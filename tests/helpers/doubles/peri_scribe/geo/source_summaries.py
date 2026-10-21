"""Inject a real source edit after complete contents have been decoded."""

from __future__ import annotations

import collections.abc
import dataclasses
import pathlib
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.geo.package


@dataclasses.dataclass(frozen=True, kw_only=True)
class ReadThenEdit:
    """Return the old complete parse after replacing its authoritative source bytes."""

    contents: dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents]

    def __call__(
        self,
        paths: collections.abc.Sequence[pathlib.Path],
        **_options: object,
    ) -> dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents]:
        """Expose the parse/publication race with real on-disk byte identities.

        Args:
            paths: Requested complete snapshots, at least one of which is present.
            **_options: Reader options accepted for interface compatibility.

        Returns:
            The complete decoded contents that preceded the source edit.
        """
        paths[0].write_bytes(b"changed after complete parse")
        return {path: self.contents[path] for path in paths}
