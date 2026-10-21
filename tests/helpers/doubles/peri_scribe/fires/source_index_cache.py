"""Interrupt real preparation after its new products have entered the transaction."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import peri_scribe.fires.grouping_cache
import peri_scribe.fires.source_index_cache
import peri_scribe.geo.package
import spatial_data.product_cache


if typing.TYPE_CHECKING:
    import collections.abc


@dataclasses.dataclass(frozen=True, kw_only=True)
class SnapshotContents:
    """Serve explicitly declared parses and retain the selected hydration paths."""

    contents: dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents]
    calls: list[tuple[pathlib.Path, ...]] = dataclasses.field(default_factory=list)

    def __call__(
        self,
        paths: collections.abc.Sequence[pathlib.Path],
        **_kwargs: object,
    ) -> dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents]:
        """Serve a test parse without interpreting the placeholder source file.

        Args:
            paths: Snapshots selected by the real incremental preparation algorithm.
            **_kwargs: Reader geometry sharing and fallback arguments.

        Returns:
            The complete declared parse for each requested snapshot.
        """
        self.calls.append(tuple(paths))
        return {path: self.contents[path] for path in paths}


@dataclasses.dataclass(frozen=True, kw_only=True)
class PreparationAbort:
    """Observe staged products before an exception forces SQLite rollback."""

    directory: pathlib.Path
    products: pathlib.Path
    manifests: list[bytes | None] = dataclasses.field(default_factory=list)
    partitions: list[tuple[str, bytes | None]] = dataclasses.field(default_factory=list)

    def __call__(self) -> None:
        """Calculate real grouping and fail before the owning transaction commits.

        Raises:
            RuntimeError: After the complete replacement products have been staged.
        """
        with spatial_data.product_cache.scope(self.products, "context"):
            staged = peri_scribe.fires.source_index_cache.prepare_index_sources(
                self.directory,
            )
            assert staged is not None
            key = peri_scribe.fires.grouping_cache.block_key(
                staged.evidence_keys,
                "0.05",
            )
            self.manifests.append(
                spatial_data.product_cache.get(
                    peri_scribe.fires.source_index_cache.NAMESPACE,
                    "current",
                ),
            )
            self.partitions.append((
                key,
                spatial_data.product_cache.get(
                    peri_scribe.fires.grouping_cache.NAMESPACE,
                    key,
                ),
            ))
            message = "abort staged index"
            raise RuntimeError(message)
