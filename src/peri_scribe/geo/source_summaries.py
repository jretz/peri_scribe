"""Retain authenticated source dependencies without decoding unchanged payloads.

Design notes:
[Authenticated parsed source cache](../../../docs/algorithms/parsed-source-cache.md).
"""

from __future__ import annotations

import collections
import collections.abc
import dataclasses
import datetime
import hashlib
import json
import pathlib
import typing

import pydantic

import peri_scribe.fires.complexes
import peri_scribe.fires.components
import peri_scribe.geo.database
import peri_scribe.geo.fingerprints
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.models
import spatial_data.geometry_pool
import spatial_data.product_cache


NAMESPACE = "source-snapshot-summary-v1"
type Digest = typing.Annotated[str, pydantic.Field(pattern=r"^[0-9a-f]{64}$")]
type AnchorOrder = tuple[str, int, str, int, int]


@dataclasses.dataclass(frozen=True, kw_only=True)
class RowSummary:
    """Keep one occurrence's complete identity and payload-free grouping metadata."""

    record: peri_scribe.models.FireRecord
    row_key: str
    anchor_order: AnchorOrder
    anchor_digest: str
    has_geometry: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class SnapshotSummary:
    """Keep source order and normalized ownership declarations for one snapshot."""

    rows: tuple[RowSummary, ...]
    memberships: tuple[peri_scribe.models.ComplexMembership, ...]
    observations: tuple[peri_scribe.fires.complexes.MembershipObservation, ...]
    row_observation_count: int


class RecordDocument(pydantic.BaseModel):
    """Decode fixed grouping fields without accepting a geometry payload."""

    model_config = pydantic.ConfigDict(strict=True, frozen=True, extra="forbid")

    name: str
    status: peri_scribe.models.FireStatus
    identifiers: frozenset[str]
    names: frozenset[str]
    observed_at: datetime.datetime | None
    mission: str | None
    point_of_origin_state: str | None
    point_of_origin_fips: str | None


class RowDocument(pydantic.BaseModel):
    """Require complete evidence identities and comparable compact anchor fields."""

    model_config = pydantic.ConfigDict(strict=True, frozen=True, extra="forbid")

    record: RecordDocument
    row_key: Digest
    anchor_order: AnchorOrder
    anchor_digest: Digest
    has_geometry: bool


class SnapshotDocument(pydantic.BaseModel):
    """Bind a completed slim projection to its authoritative path and byte identity."""

    model_config = pydantic.ConfigDict(strict=True, frozen=True, extra="forbid")

    path: str
    checksum: Digest
    rows: tuple[RowDocument, ...]
    memberships: tuple[peri_scribe.models.ComplexMembership, ...]
    observations: tuple[peri_scribe.fires.complexes.MembershipObservation, ...]
    row_observation_count: pydantic.NonNegativeInt

    @pydantic.model_validator(mode="after")
    def observation_partition(self) -> typing.Self:
        """Keep row declarations before membership fallbacks when snapshots combine.

        Returns:
            This document when its boundary is inside the complete observation tuple.

        Raises:
            ValueError: If the boundary points beyond the retained observations.
        """
        if self.row_observation_count > len(self.observations):
            message = "Row declaration count exceeds complete snapshot observations"
            raise ValueError(message)
        return self


def snapshot_key(path: pathlib.Path, directory: pathlib.Path, checksum: str) -> str:
    """Distinguish equal snapshot bytes retained at different provenance paths.

    Args:
        path: One retained source snapshot.
        directory: Source root used for stable relative provenance.
        checksum: Freshly authenticated authoritative source identity.

    Returns:
        The complete ordered path/content identity within the product context.
    """
    return hashlib.sha256(
        json.dumps((str(path.relative_to(directory)), checksum)).encode(),
    ).hexdigest()


def summarize(
    path: pathlib.Path,
    contents: peri_scribe.geo.package.GeopackageContents,
) -> SnapshotSummary:
    """Project one complete parse while retaining exact component anchor behavior.

    Token ranks are comparable within their source/serial/filename prefix in this
    snapshot. Consumers must reject distinct paths sharing that prefix before comparing
    their ranks. Each digest is the original full singleton anchor's component identity.

    Args:
        path: The snapshot supplying the complete parse and collection clock.
        contents: Full validated rows and memberships in authoritative source order.

    Returns:
        The payload-free dependency and ownership evidence for every occurrence.
    """
    paths = (path,) * len(contents.rows)
    anchors = peri_scribe.fires.components.anchors(contents.rows, paths)
    tokens: dict[tuple[str, int, str], set[str]] = collections.defaultdict(set)
    for source, serial, filename, token, _occurrence in anchors:
        tokens[source, serial, filename].add(token)
    ranks = {
        prefix: {token: rank for rank, token in enumerate(sorted(values))}
        for prefix, values in tokens.items()
    }
    return SnapshotSummary(
        rows=tuple(
            RowSummary(
                record=dataclasses.replace(row.record, geometry=None),
                row_key=peri_scribe.geo.fingerprints.row_evidence_fingerprint(row),
                anchor_order=(
                    anchor[0],
                    anchor[1],
                    anchor[2],
                    ranks[anchor[:3]][anchor[3]],
                    anchor[4],
                ),
                anchor_digest=peri_scribe.fires.components.component_id([anchor]),
                has_geometry=row.record.geometry is not None,
            )
            for row, anchor in zip(contents.rows, anchors, strict=True)
        ),
        memberships=contents.memberships,
        observations=tuple(
            peri_scribe.fires.complexes.observations(
                contents.rows,
                paths,
                contents.memberships,
                (path,) * len(contents.memberships),
            ),
        ),
        row_observation_count=sum(
            peri_scribe.fires.complexes.row_observation(row, path) is not None
            for row in contents.rows
        ),
    )


def store_summary(
    path: pathlib.Path,
    directory: pathlib.Path,
    checksum: str,
    summary: SnapshotSummary,
) -> None:
    """Store a complete projection using the existing authenticated product protocol.

    Args:
        path: The authoritative source snapshot.
        directory: Root used to bind relative provenance.
        checksum: Its freshly authenticated complete byte identity.
        summary: The complete projection constructed from its validated parse.
    """
    document = SnapshotDocument(
        path=str(path.relative_to(directory)),
        checksum=checksum,
        rows=tuple(
            RowDocument(
                record=RecordDocument(**{
                    field.name: getattr(row.record, field.name)
                    for field in dataclasses.fields(row.record)
                    if field.name != "geometry"
                }),
                row_key=row.row_key,
                anchor_order=row.anchor_order,
                anchor_digest=row.anchor_digest,
                has_geometry=row.has_geometry,
            )
            for row in summary.rows
        ),
        memberships=summary.memberships,
        observations=summary.observations,
        row_observation_count=summary.row_observation_count,
    )
    spatial_data.product_cache.put(
        NAMESPACE,
        snapshot_key(path, directory, checksum),
        document.model_dump_json().encode(),
    )


def read_snapshot_summary(
    path: pathlib.Path,
    directory: pathlib.Path,
    checksum: str,
) -> SnapshotSummary | None:
    """Accept only completed current-context summaries matching current source bytes.

    Args:
        path: The current authoritative source snapshot.
        directory: Root defining its relative provenance identity.
        checksum: A freshly authenticated source checksum from the owning scope.

    Returns:
        The complete decoded projection, or None for a disposable cache miss.
    """
    payload = spatial_data.product_cache.get(
        NAMESPACE,
        snapshot_key(path, directory, checksum),
    )
    if payload is None:
        return None
    try:
        document = SnapshotDocument.model_validate_json(payload)
    except pydantic.ValidationError:
        return None
    if (
        document.path != str(path.relative_to(directory))
        or document.checksum != checksum
    ):
        return None
    return SnapshotSummary(
        rows=tuple(
            RowSummary(
                record=peri_scribe.models.FireRecord(**row.record.model_dump()),
                row_key=row.row_key,
                anchor_order=row.anchor_order,
                anchor_digest=row.anchor_digest,
                has_geometry=row.has_geometry,
            )
            for row in document.rows
        ),
        memberships=document.memberships,
        observations=document.observations,
        row_observation_count=document.row_observation_count,
    )


def read_summaries(
    paths: collections.abc.Sequence[pathlib.Path],
    directory: pathlib.Path,
    *,
    geometry_pool: spatial_data.geometry_pool.GeometryPool,
    read_fallback: collections.abc.Callable[
        [pathlib.Path],
        peri_scribe.geo.package.GeopackageContents,
    ]
    | None = None,
) -> tuple[
    dict[pathlib.Path, SnapshotSummary],
    dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents],
]:
    """Authenticate every source but hydrate only absent or invalid summary products.

    Args:
        paths: Current snapshots in authoritative inventory order.
        directory: Their common source provenance root.
        geometry_pool: Shared geometries for any changed or unavailable snapshots.
        read_fallback: Optional authoritative parser retaining caller error translation.

    Returns:
        Complete summaries and full contents only for the snapshots hydrated on misses.
    """
    checksums = {
        path: peri_scribe.geo.database.snapshot_checksum(path) for path in paths
    }
    summaries = {
        path: summary
        for path in paths
        if (summary := read_snapshot_summary(path, directory, checksums[path]))
        is not None
    }
    missing = [path for path in paths if path not in summaries]
    hydrated = peri_scribe.geo.reading.read_geopackages_cached(
        missing,
        geometry_pool=geometry_pool,
        read_fallback=read_fallback,
    )
    verify_checksums({path: checksums[path] for path in missing})
    for path in missing:
        summary = summarize(path, hydrated[path])
        store_summary(path, directory, checksums[path], summary)
        summaries[path] = summary
    return {path: summaries[path] for path in paths}, hydrated


def verify_checksums(checksums: collections.abc.Mapping[pathlib.Path, str]) -> None:
    """Reject source changes before binding a complete parse to durable evidence.

    Args:
        checksums: Authoritative identities captured before the complete source parse.

    Raises:
        OSError: If current source bytes differ from the parse-bound identities.
    """
    for path, checksum in checksums.items():
        if peri_scribe.geo.database.snapshot_checksum(path) != checksum:
            message = f"Source changed during preparation: {path}"
            raise OSError(message)


def seed_summaries(
    directory: pathlib.Path,
    contents_by_path: collections.abc.Mapping[
        pathlib.Path,
        peri_scribe.geo.package.GeopackageContents,
    ],
    checksums: collections.abc.Mapping[pathlib.Path, str],
) -> None:
    """Seed later selective reads from an already complete source-index preparation.

    Args:
        directory: Source root used for stable provenance.
        contents_by_path: Complete parsed contents from the current full preparation.
        checksums: Complete path identities captured before that full source parse.

    Raises:
        ValueError: If the parse and authenticated inventory describe different paths.
    """
    if contents_by_path.keys() != checksums.keys():
        message = "Source summary contents and authenticated paths must agree"
        raise ValueError(message)
    verify_checksums(checksums)
    for path, contents in contents_by_path.items():
        store_summary(
            path,
            directory,
            checksums[path],
            summarize(path, contents),
        )
