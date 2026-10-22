"""Check complete evidence returned by the named raw-row adapter."""

import dataclasses

import pytest
import shapely

import peri_scribe.geo.fingerprints
import peri_scribe.geo.package
import peri_scribe.models
import spatial_data.geometry_pool
import tests.helpers.factories.peri_scribe.geo.catalog
import tests.helpers.factories.peri_scribe.geo.package


@pytest.mark.parametrize(
    "geometry",
    [None, shapely.set_srid(shapely.Point(-0.0, 45, 17), 4326)],
)
def test_fire_row_record_from_row_restores_exact_evidence(
    geometry: shapely.Geometry | None,
) -> None:
    source = tests.helpers.factories.peri_scribe.geo.catalog.rows()[0]
    source = dataclasses.replace(
        source,
        record=dataclasses.replace(
            source.record,
            geometry=geometry,
            names=frozenset({"park", "park fire"}),
            identifiers=frozenset({"fire-0", "2026-ca-000123"}),
            mission="Survey 7",
            point_of_origin_state="US-CA",
            point_of_origin_fips="06035",
        ),
        attributes={"nested": [0, None, True, {"area": -0.0, "label": "火"}]},
    )
    stored = tests.helpers.factories.peri_scribe.geo.package.cache_row(source)
    decoded = peri_scribe.geo.package.FireRowRecord.from_row(
        stored,
        geometry_pool=spatial_data.geometry_pool.GeometryPool(),
    )
    assert decoded == source
    assert decoded.to_row(7) == source.to_row(7)
    assert isinstance(decoded.record.identifiers, frozenset)
    assert isinstance(decoded.record.names, frozenset)
    assert decoded.record.status is peri_scribe.models.FireStatus.ACTIVE
    assert decoded.evidence_fingerprint == stored["evidence_fingerprint"]
    assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(decoded) == (
        peri_scribe.geo.fingerprints.complete_row_fingerprint(source)
    )


def test_fire_row_record_from_row_retains_independent_mutation_guards() -> None:
    source = tests.helpers.factories.peri_scribe.geo.catalog.rows()[0]
    stored = tests.helpers.factories.peri_scribe.geo.package.cache_row(source)
    pool = spatial_data.geometry_pool.GeometryPool()
    first = peri_scribe.geo.package.FireRowRecord.from_row(stored, geometry_pool=pool)
    second = peri_scribe.geo.package.FireRowRecord.from_row(stored, geometry_pool=pool)
    nested = first.attributes["nested"]
    assert isinstance(nested, list)
    nested[0] = False
    assert first.evidence_basis is not None
    assert first.evidence_basis.attributes == source.attributes == second.attributes
    assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(first) == (
        peri_scribe.geo.fingerprints.complete_row_fingerprint(first)
    )
    assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(first) != (
        first.evidence_fingerprint
    )
    assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(second) == (
        second.evidence_fingerprint
    )


@pytest.mark.parametrize(
    ("column", "changed"),
    [
        ("evidence_fingerprint", "invalid"),
        ("geometry_wkb", shapely.to_wkb(shapely.Point(1, 1))),
        ("attributes_json", '{"nested": [false, null, true]}'),
        ("status", peri_scribe.models.FireStatus.INACTIVE.value),
        ("object_id", 44),
    ],
)
def test_fire_row_record_from_row_rejects_changed_stored_evidence(
    column: str,
    changed: object,
) -> None:
    source = tests.helpers.factories.peri_scribe.geo.catalog.rows()[0]
    stored = tests.helpers.factories.peri_scribe.geo.package.cache_row(
        source,
        **{column: changed},
    )
    with pytest.raises(ValueError, match="fingerprint does not match"):
        peri_scribe.geo.package.FireRowRecord.from_row(
            stored,
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )
