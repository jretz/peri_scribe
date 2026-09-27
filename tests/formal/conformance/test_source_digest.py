"""Source comparisons agree with prefix-free, schema-aware content identity."""

from __future__ import annotations

import pathlib
import typing

import geopandas

import peri_scribe.sources.catalog
import peri_scribe.sources.digests
import peri_scribe.sources.external_sources
import spatial_data.layers
import tests.formal.helpers.source_digest


if typing.TYPE_CHECKING:
    import pytest


def test_framed_value_matches_proved_byte_encoding() -> None:
    cases = tests.formal.helpers.source_digest.framing_cases()
    expected = tests.formal.helpers.source_digest.encode(cases)
    for parts, encoded in zip(cases, expected, strict=True):
        assert b"".join(map(peri_scribe.sources.digests.framed_value, parts)) == encoded
    assert len(set(expected)) == len(set(cases))


def test_digest_value_matches_declared_source_normalization() -> None:
    for case in tests.formal.helpers.source_digest.scalars():
        assert peri_scribe.sources.digests.digest_value(case.value) == case.fragment


def test_dataframe_digest_matches_proved_framing_and_row_canonicalization() -> None:
    fixtures = tests.formal.helpers.source_digest.cases()
    expected = tests.formal.helpers.source_digest.expected_fingerprints(fixtures)
    actual = [
        peri_scribe.sources.digests.dataframe_digest(case.value) for case in fixtures
    ]
    assert actual == expected


def test_dataframe_digest_equality_matches_proved_semantic_equivalence() -> None:
    fixtures = tests.formal.helpers.source_digest.cases()
    actual = [
        peri_scribe.sources.digests.dataframe_digest(case.value) for case in fixtures
    ]
    for first, second, equal in tests.formal.helpers.source_digest.equivalences(
        fixtures,
    ):
        assert (actual[first] == actual[second]) == equal


def test_snapshot_matches_preserves_real_geopackage_content_identity(
    tmp_path: pathlib.Path,
) -> None:
    values = tests.formal.helpers.source_digest.scalars()
    selected = tuple(value for value in values if isinstance(value.value, str))
    frame = tests.formal.helpers.source_digest.frame(
        ("first", "second"),
        ((selected[1], selected[4]), (selected[2], selected[3])),
    ).value
    path = tmp_path / "external.gpkg"
    spatial_data.layers.write_geopackage(
        path,
        [spatial_data.layers.LayerData(name="features", dataframe=frame)],
    )
    assert peri_scribe.sources.digests.snapshot_matches(
        frame.iloc[::-1],
        path,
        "features",
    )
    changed = frame.copy()
    changed.loc[0, "first"] = "as"
    changed.loc[0, "second"] = "b"
    assert not peri_scribe.sources.digests.snapshot_matches(changed, path, "features")
    assert not peri_scribe.sources.digests.snapshot_matches(
        geopandas.GeoDataFrame(frame.rename(columns={"first": "other"})),
        path,
        "features",
    )


def test_fetch_arcgis_source_publishes_changes_with_equal_unframed_bytes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scalar = tests.formal.helpers.source_digest.Scalar
    old = tests.formal.helpers.source_digest.frame(
        ("first", "second"),
        ((scalar(value="a", fragment=b"sa"), scalar(value="sb", fragment=b"ssb")),),
    ).value
    new = tests.formal.helpers.source_digest.frame(
        ("first", "second"),
        ((scalar(value="as", fragment=b"sas"), scalar(value="b", fragment=b"sb")),),
    ).value
    incoming = iter((old, new, new))
    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "query_arcgis_source",
        lambda _source: next(incoming),
    )
    source = peri_scribe.sources.catalog.EVACUATIONS_SOURCE
    path = peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
    before = path.read_bytes()
    assert (
        peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
        == path
    )
    assert path.read_bytes() != before
    current = geopandas.read_file(path, layer="evacuations")
    assert current[["first", "second"]].values.tolist() == [["as", "b"]]
    published = path.stat().st_mtime_ns
    peri_scribe.sources.external_sources.fetch_arcgis_source(source, tmp_path)
    assert path.stat().st_mtime_ns == published
