"""Connect complete source keys to Lean and actual cached border classification."""

from __future__ import annotations

import dataclasses
import datetime
import functools
import pathlib

import pytest
import shapely
import shapely.affinity

import peri_scribe.fires.index
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.perimeters.border_classification
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.snapshots
import spatial_data.cache_values
import tests.formal.helpers.cache_dependencies
import tests.helpers.factories.peri_scribe.models
import tests.helpers.factories.peri_scribe.perimeters.classification


CONTRACT = tests.formal.helpers.cache_dependencies.Contract(
    namespace=peri_scribe.fires.index.CLASSIFICATION_NAMESPACE,
    consumed=(
        "attributes",
        "attribute_type",
        "object_id",
        "source_name",
        "path",
        "order",
        "removal",
        "name",
        "status",
        "identifiers",
        "names",
        "geometry",
        "srid",
        "time",
        "mission",
        "origin_state",
        "origin_fips",
        "aliases",
        "membership",
        "membership_name",
        "member_set",
        "boundary",
        "code",
        "runtime",
    ),
    wrappers=("attribute_order",),
)
PRIMARY = "id-primary"
SIBLING = "id-sibling"
FEED = "WFIGS_Interagency_Perimeters"
SIBLING_ROW = 2


def record(index: int, change: str) -> peri_scribe.models.FireRecord:
    """Vary one observation field while retaining one identifiable component fire.

    Args:
        index: The observation's stable sequence identity.
        change: One declared dependency or an empty string for baseline evidence.

    Returns:
        A real fire record suitable for grouping and border classification.
    """
    observed = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
    value = tests.helpers.factories.peri_scribe.models.fire_record(
        "Sibling" if index == SIBLING_ROW else "Primary",
        peri_scribe.models.FireStatus.ACTIVE,
        identifiers={SIBLING if index == SIBLING_ROW else PRIMARY},
        geometry=shapely.box(-120, 38, -119.8 + index * 0.02, 38.2),
        observed_at=observed + datetime.timedelta(hours=index),
    )
    if index != 0:
        return value
    match change:
        case "name":
            value = dataclasses.replace(value, name="Changed")
        case "status":
            value = dataclasses.replace(
                value,
                status=peri_scribe.models.FireStatus.INACTIVE,
            )
        case "identifiers":
            value = dataclasses.replace(
                value,
                identifiers=value.identifiers | {"extra"},
            )
        case "names":
            value = dataclasses.replace(value, names=value.names | {"changed"})
        case "geometry":
            value = dataclasses.replace(
                value,
                geometry=shapely.box(-119.1, 38, -118.9, 39),
            )
        case "srid":
            value = dataclasses.replace(
                value,
                geometry=shapely.set_srid(value.geometry, 4326),
            )
        case "time":
            value = dataclasses.replace(
                value,
                observed_at=observed - datetime.timedelta(days=1),
            )
        case "mission":
            value = dataclasses.replace(value, mission="NV-ELY-PRIMARY")
        case "origin_state":
            value = dataclasses.replace(value, point_of_origin_state="NV")
        case "origin_fips":
            value = dataclasses.replace(value, point_of_origin_fips="32001")
    return value


def source_row(index: int, change: str) -> peri_scribe.geo.package.FireRowRecord:
    """Retain raw source attributes separately from parsed fire metadata.

    Args:
        index: The original row ordinal, also used as a source object identifier.
        change: A dependency mutation or an empty baseline selector.

    Returns:
        Complete source evidence whose attributes may conservatively invalidate reuse.
    """
    attributes: dict[str, object] = {"reported": index, "other": "retained"}
    if index == 0:
        if change == "attributes":
            attributes["reported"] = 99
        if change == "attribute_type":
            attributes["reported"] = "0"
        if change == "attribute_order":
            attributes = dict(reversed(tuple(attributes.items())))
    return peri_scribe.geo.package.FireRowRecord(
        record=record(index, change),
        object_id=99 if index == 0 and change == "object_id" else index,
        source_name="Changed" if index == 0 and change == "source_name" else FEED,
        attributes=attributes,
    )


def prepared_sources(
    year: pathlib.Path,
    change: str,
) -> peri_scribe.fires.sources.PreparedSources:
    """Use actual grouping, then select one component as classification does on misses.

    The second component remains in the complete source read so changing aggregate
    membership exercises a transitive key dependency without adding a second lookup.

    Args:
        year: The source-root owner for relative provenance.
        change: One evidence, provenance, or membership mutation.

    Returns:
        Complete source evidence and the selected component's real grouped identity.
    """
    root = peri_scribe.sources.snapshots.sources_directory_path(year)
    indices = (1, 0, 2) if change == "order" else (0, 1, 2)
    if change == "removal":
        indices = (1, 2)
    paths = tuple(
        root
        / FEED
        / peri_scribe.sources.snapshots.SourceFile(
            serial_number=index + (10 if index == 0 and change == "path" else 0),
            last_edit_timestamp=1_700_000_000_000 + index,
        ).relative_path
        for index in indices
    )
    parent = "other-parent" if change == "membership" else "parent"
    name = "Changed Complex" if change == "membership_name" else "Parent Complex"
    memberships = tuple(
        peri_scribe.models.ComplexMembership(
            fire_identifier=identifier,
            complex_identifier=parent,
            complex_name=name,
        )
        for identifier in ((PRIMARY, SIBLING) if change == "member_set" else (PRIMARY,))
    )
    read = peri_scribe.fires.sources.ReadFireSources(
        rows=tuple(source_row(index, change) for index in indices),
        paths=paths,
        memberships=memberships,
    )
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    ((fire, group),) = (
        (fire, group)
        for fire, group in zip(groups.fires, groups.groups, strict=True)
        if PRIMARY in fire.aliases
    )
    if change == "aliases":
        # Isolate the grouped alias field from the already covered raw record IDs.
        previous = fire
        fire = dataclasses.replace(fire, aliases=fire.aliases | {"presentation-alias"})
        assert previous.complex is not None
        peri_scribe.models.FireComplex(
            name=previous.complex.name,
            identifier=previous.complex.identifier,
            fires=(previous.complex.fires - {previous}) | {fire},
        )
    groups = dataclasses.replace(groups, fires=(fire,), groups=(group,))
    return peri_scribe.fires.sources.PreparedSources(read=read, groups=groups)


def classify(directory: pathlib.Path, change: str) -> bytes:
    """Run actual projection, geometry signals, classification, and persistent reuse.

    Only boundary loading is replaced by a synthetic projected boundary; classification
    itself, source grouping, source fingerprints, SQLite, and serialization remain real.

    Args:
        directory: Isolated source context and authoritative dependency bytes.
        change: One field mutation or an empty baseline selector.

    Returns:
        Every serialized classification field in deterministic component order.
    """
    year = directory / "2026"
    source = directory / "src" / "peri_scribe" / "fires" / "reuse.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# other\n" if change == "code" else "# first\n")
    boundary = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        year,
    )
    boundary.parent.mkdir(parents=True, exist_ok=True)
    boundary.write_bytes(b"changed" if change == "boundary" else b"initial")
    boundary_factory = tests.helpers.factories.peri_scribe.perimeters.classification
    projected = boundary_factory.projected_boundaries()
    if change == "boundary":
        projected = dataclasses.replace(
            projected,
            box=shapely.affinity.translate(projected.box, xoff=500_000),
            border=shapely.affinity.translate(projected.border, xoff=500_000),
        )
    prepared = prepared_sources(year, change)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(peri_scribe.fires.reuse, "__file__", str(source))
        monkeypatch.setattr(
            peri_scribe.perimeters.border_classification,
            "load_boundaries",
            lambda _year: projected,
        )
        result = peri_scribe.fires.index.classifications_for_prepared_sources(
            year,
            prepared,
        )
    return spatial_data.cache_values.dumps(
        tuple(
            result[id(fire)].model_dump(mode="json") for fire in prepared.groups.fires
        ),
    )


def compare(directory: pathlib.Path, change: str) -> None:
    """Require each actual source-key transition to obey the proved cache contract.

    Args:
        directory: Isolated persistent cache, synthetic code, and source dependencies.
        change: The dependency mutation compared with Lean's projected input change.
    """
    tests.formal.helpers.cache_dependencies.check_transition(
        directory,
        CONTRACT,
        change,
        functools.partial(classify, directory, ""),
        functools.partial(classify, directory, change),
    )
