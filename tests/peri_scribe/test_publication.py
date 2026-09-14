"""Publication decisions must survive skipped downloads and failed output writes."""

from __future__ import annotations

import datetime
import pathlib

import geopandas
import pytest
import shapely
import time_machine

import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.publication
import peri_scribe.sources.external_sources
import peri_scribe.sources.feeds
import peri_scribe.units
import tests.factories
from peri_scribe.units import units


NOW = datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC)
STAMP = peri_scribe.publication.FileStamp(size=1, modified_nanoseconds=1)
THRESHOLD = peri_scribe.publication.Threshold(
    area=25.0 * units.acres,
    interval=datetime.timedelta(minutes=5),
)


def mapping(
    acres: float | None,
    *,
    serial: int = 1,
    identifiers: tuple[str, ...] = ("a",),
    captured_at: datetime.datetime = NOW,
) -> peri_scribe.publication.Mapping:
    """Construct source observations with deliberately distinct capture and map dates.

    Args:
        acres: The raw mapped area in acres, or None for an unmeasurable mapping.
        serial: The snapshot serial used to distinguish and order observations.
        identifiers: The fire identifiers associated with the mapping.
        captured_at: The local first-capture time used for provenance.

    Returns:
        A raw source measurement suitable for persisted checkpoints.
    """
    return peri_scribe.publication.Mapping(
        source_file=f"snapshot-{serial}",
        object_id=serial,
        identifiers=identifiers,
        name="Example",
        observed_at=NOW + datetime.timedelta(minutes=serial),
        captured_at=captured_at,
        serial=serial,
        shape=str(acres),
        area_square_meters=(acres * units.acres).m_as("meters ** 2")
        if acres is not None
        else None,
    )


def collection(
    *mappings: peri_scribe.publication.Mapping,
) -> peri_scribe.publication.Collection:
    """Retain each downloaded snapshot independently of publication.

    Args:
        *mappings: Source observations to include in the downloaded inventory.

    Returns:
        A complete source inventory containing these observations.
    """
    return peri_scribe.publication.Collection(
        files={item.source_file: STAMP for item in mappings},
        mappings={item.source_file: (item,) for item in mappings},
    )


def publication(
    baseline: peri_scribe.publication.Mapping | None,
) -> peri_scribe.publication.Publication:
    """Publication knows which source files were actually processed.

    Args:
        baseline: The previously displayed mapping, or None for an excluded fire.

    Returns:
        The completed baseline, including the zero baseline for excluded fires.
    """
    return peri_scribe.publication.Publication(
        created_at=NOW,
        output=STAMP,
        files={} if baseline is None else {baseline.source_file: STAMP},
        fires={
            "id:a": peri_scribe.publication.PublishedFire(
                identifiers=("a", "alias"),
                name="Example",
                mapping=baseline,
            ),
        },
    )


@pytest.mark.parametrize(
    ("area", "proceed"),
    [(124.99, False), (125.0, True), (125.01, True), (75.0, True), (75.01, False)],
)
def test_gate_includes_threshold_in_both_directions(
    area: float,
    *,
    proceed: bool,
) -> None:
    baseline = mapping(100)
    decision = peri_scribe.publication.decide(
        collection(baseline, mapping(area, serial=2)),
        publication(baseline),
        THRESHOLD,
        NOW,
    )
    assert decision.proceed is proceed
    assert decision.change.m_as("acres") == pytest.approx(area - 100)


def test_small_skipped_changes_accumulate_against_published_area() -> None:
    baseline = mapping(100)
    published = publication(baseline)
    saved = collection(baseline, mapping(115, serial=2))
    assert not peri_scribe.publication.decide(saved, published, THRESHOLD, NOW).proceed
    saved = collection(baseline, mapping(115, serial=2), mapping(130, serial=3))
    decision = peri_scribe.publication.decide(saved, published, THRESHOLD, NOW)
    assert decision.proceed
    assert decision.change.m_as("acres") == pytest.approx(30)
    assert published.fires["id:a"].mapping == baseline


def test_latest_correction_replaces_an_unpublished_spike() -> None:
    baseline = mapping(100)
    saved = collection(baseline, mapping(600, serial=2), mapping(101, serial=3))
    decision = peri_scribe.publication.decide(
        saved,
        publication(baseline),
        THRESHOLD,
        NOW,
    )
    assert not decision.proceed
    assert decision.change.m_as("acres") == pytest.approx(1)


def test_late_old_mapping_does_not_displace_newer_published_map() -> None:
    baseline = mapping(100, serial=3)
    saved = collection(baseline, mapping(1, serial=2))
    assert not peri_scribe.publication.decide(
        saved,
        publication(baseline),
        THRESHOLD,
        NOW,
    ).proceed


@pytest.mark.parametrize("baseline", [None, mapping(100)])
def test_new_unmapped_fire_compares_with_zero(
    baseline: peri_scribe.publication.Mapping | None,
) -> None:
    candidates = peri_scribe.publication.candidate_fires(
        [mapping(25, identifiers=("new",))],
        publication(baseline),
    )
    assert peri_scribe.publication.mapping_decision(candidates, THRESHOLD).proceed


def test_excluded_fire_has_zero_published_area() -> None:
    candidates = peri_scribe.publication.candidate_fires(
        [mapping(25)],
        publication(None),
    )
    assert peri_scribe.publication.mapping_decision(candidates, THRESHOLD).proceed


def test_gate_uses_aliases_and_is_independent_of_snapshot_iteration_order() -> None:
    baseline = mapping(100)
    candidates = peri_scribe.publication.candidate_fires(
        [mapping(130, serial=3, identifiers=("alias",)), mapping(110, serial=2)],
        publication(baseline),
    )
    assert candidates is not None
    assert set(candidates) == {"id:a"}
    assert peri_scribe.publication.mapping_decision(candidates, THRESHOLD).change.m_as(
        "acres",
    ) == pytest.approx(30)


@pytest.mark.parametrize("identifiers", [(), ("a", "b")])
def test_ambiguous_identity_requires_build(identifiers: tuple[str, ...]) -> None:
    published = publication(mapping(100))
    published = published.model_copy(
        update={
            "fires": {
                **published.fires,
                "id:b": peri_scribe.publication.PublishedFire(
                    identifiers=("b",),
                    name="Other",
                    mapping=None,
                ),
            },
        },
    )
    candidates = peri_scribe.publication.candidate_fires(
        [mapping(1, identifiers=identifiers)],
        published,
    )
    decision = peri_scribe.publication.mapping_decision(candidates, THRESHOLD)
    assert decision.proceed
    assert decision.reason == peri_scribe.publication.Reason.UNCERTAIN_MAPPING


@pytest.mark.parametrize(("before", "after"), [(None, 100), (100, None)])
def test_unmeasurable_geometry_requires_build(
    before: float | None,
    after: float | None,
) -> None:
    baseline = mapping(before)
    decision = peri_scribe.publication.decide(
        collection(baseline, mapping(after, serial=2)),
        publication(baseline),
        THRESHOLD,
        NOW,
    )
    assert decision.proceed
    assert decision.reason == peri_scribe.publication.Reason.UNCERTAIN_MAPPING


@pytest.mark.parametrize("seconds", [299, 300, 301])
def test_timer_fires_on_saved_updates_even_without_new_downloads(seconds: int) -> None:
    baseline = mapping(100)
    saved = collection(baseline, mapping(100, serial=2))
    decision = peri_scribe.publication.decide(
        saved,
        publication(baseline),
        THRESHOLD,
        NOW + datetime.timedelta(seconds=seconds),
    )
    assert decision.proceed is (
        datetime.timedelta(seconds=seconds) >= THRESHOLD.interval
    )
    assert decision.reason == (
        peri_scribe.publication.Reason.TIMER
        if datetime.timedelta(seconds=seconds) >= THRESHOLD.interval
        else peri_scribe.publication.Reason.BELOW_THRESHOLD
    )


def test_unchanged_inputs_stay_skipped_after_timer_expires() -> None:
    baseline = mapping(100)
    decision = peri_scribe.publication.decide(
        collection(baseline),
        publication(baseline),
        THRESHOLD,
        NOW + datetime.timedelta(hours=6),
    )
    assert decision.reason == peri_scribe.publication.Reason.NO_CHANGES
    assert not decision.proceed


def test_incident_updates_wait_for_timer() -> None:
    saved = peri_scribe.publication.Collection(
        files={"points": STAMP},
        mappings={"points": ()},
    )
    assert not peri_scribe.publication.decide(
        saved,
        publication(None),
        THRESHOLD,
        NOW,
    ).proceed
    assert peri_scribe.publication.decide(
        saved,
        publication(None),
        THRESHOLD,
        NOW + THRESHOLD.interval,
    ).proceed


@pytest.mark.parametrize(
    "reason",
    [
        peri_scribe.publication.Reason.NO_PUBLICATION,
        peri_scribe.publication.Reason.SOURCE_HISTORY,
        peri_scribe.publication.Reason.EVACUATIONS,
    ],
)
def test_missing_checkpoint_or_changed_acknowledged_inputs_require_build(
    reason: peri_scribe.publication.Reason,
) -> None:
    published = publication(mapping(100))
    saved = peri_scribe.publication.Collection()
    if reason == peri_scribe.publication.Reason.EVACUATIONS:
        saved = saved.model_copy(update={"evacuations": STAMP})
    decision = peri_scribe.publication.decide(
        saved,
        None if reason == peri_scribe.publication.Reason.NO_PUBLICATION else published,
        THRESHOLD,
        NOW,
    )
    assert decision.proceed
    assert decision.reason == reason


def test_checkpoint_requires_matching_completed_output(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "output.kmz"
    assert peri_scribe.publication.read_publication(tmp_path, output) is None
    peri_scribe.publication.write_state(
        peri_scribe.publication.publication_path(tmp_path),
        publication(None),
    )
    assert peri_scribe.publication.read_publication(tmp_path, output) is None
    output.write_bytes(b"complete")
    assert peri_scribe.publication.read_publication(tmp_path, output) is None
    baseline = mapping(100)
    with time_machine.travel(NOW, tick=False):
        peri_scribe.publication.commit(
            tmp_path,
            output,
            collection(baseline),
            publication(baseline).fires,
        )
    loaded = peri_scribe.publication.read_publication(tmp_path, output)
    assert loaded is not None
    assert loaded.created_at == NOW
    assert loaded.fires["id:a"].mapping == baseline
    output.write_bytes(b"manually regenerated")
    assert peri_scribe.publication.read_publication(tmp_path, output) is None


def test_corrupt_state_cannot_authorize_skip(tmp_path: pathlib.Path) -> None:
    state = tmp_path / "state.json"
    state.write_text('{"version": 2}')
    assert (
        peri_scribe.publication.read_state(state, peri_scribe.publication.Collection)
        is None
    )


def test_failed_checkpoint_replacement_preserves_previous_state(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state.json"
    state.write_bytes(b"previous")
    monkeypatch.setattr(
        pathlib.Path,
        "replace",
        tests.factories.raising_stub(OSError("disk failure")),
    )
    with pytest.raises(OSError, match="disk failure"):
        peri_scribe.publication.write_state(state, collection())
    assert state.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [state]


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        shapely.Polygon(),
        shapely.Point(0, 0),
        shapely.Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)]),
    ],
)
def test_unusable_geometries_are_explicitly_unknown(
    geometry: shapely.Geometry | None,
) -> None:
    _digest, area = peri_scribe.publication.shape_measurement(geometry)
    assert area is None


def test_multipart_ring_directions_do_not_cancel_area() -> None:
    left = shapely.box(-121, 40, -120.99, 40.01)
    right = shapely.box(-120, 40, -119.99, 40.01)
    geometry = shapely.MultiPolygon([left, shapely.reverse(right)])
    digest, area = peri_scribe.publication.shape_measurement(geometry)
    assert digest
    expected = peri_scribe.units.area(left) + peri_scribe.units.area(right)
    assert area == pytest.approx(expected.m_as("meters ** 2"))


def test_nonfinite_area_cannot_authorize_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        peri_scribe.units,
        "area",
        lambda _geometry: float("nan") * units.meters**2,
    )
    assert peri_scribe.publication.shape_measurement(shapely.box(0, 0, 1, 1))[1] is None


def test_attribute_republication_keeps_first_capture_and_unknown_ids_do_not_merge() -> (
    None
):
    first = mapping(100, captured_at=NOW - datetime.timedelta(hours=1))
    second = mapping(100, serial=2, identifiers=("a", "alias"))
    unknown = mapping(100, serial=3, identifiers=())
    captures = peri_scribe.publication.first_captures(
        collection(first, second, unknown).mappings,
    )
    assert captures[second.source_file][0].captured_at == first.captured_at
    assert captures[unknown.source_file][0].captured_at == NOW
    undated = unknown.model_copy(update={"observed_at": None, "object_id": None})
    assert peri_scribe.publication.mapping_order(undated) == (
        peri_scribe.models.EARLIEST_DATETIME,
        3,
        -1,
    )


def test_snapshot_reader_reprojects_and_ignores_incident_rows(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    frame = geopandas.GeoDataFrame(
        {
            "attr_IncidentName": ["Example", None],
            "attr_ActiveFireCandidate": [1, 1],
            "poly_IRWINID": ["{A}", None],
            "attr_UniqueFireIdentifier": ["Alias", None],
            "poly_DateCurrent": [NOW, NOW],
            "attr_POOState": [None, None],
            "attr_POOFips": [None, None],
            "OBJECTID": [123, 124],
        },
        geometry=[shapely.box(-121, 40, -120.99, 40.01)] * 2,
        crs=4326,
    ).to_crs(3857)
    monkeypatch.setattr(
        peri_scribe.geo.package,
        "layers_by_feed",
        lambda _path: [
            (peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED, frame),
            (feed, frame),
        ],
    )
    path = tmp_path / feed.name / "000___/000001,lastEdit=1789257600000.gpkg"
    (observed,) = peri_scribe.publication.snapshot_mappings(path, tmp_path, NOW)
    assert observed.identifiers == ("a", "alias")
    assert observed.object_id == frame.iloc[0]["OBJECTID"]
    assert observed.source_file == str(path.relative_to(tmp_path))
    assert observed.area is not None
    assert observed.area > THRESHOLD.area


def test_collection_reuses_measurements_and_retains_skipped_snapshots(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    first = sources / "000001,lastEdit=1.gpkg"
    first.write_bytes(b"first")
    reads: list[pathlib.Path] = []

    def measure(
        path: pathlib.Path,
        _sources: pathlib.Path,
        captured: datetime.datetime,
    ) -> tuple[peri_scribe.publication.Mapping, ...]:
        """Record expensive reads while exercising real inventory and cache I/O.

        Args:
            path: The source snapshot whose measurement request is recorded.
            _sources: The sources root accepted to match the reader's signature; unused.
            captured: The actual capture time supplied by collection.

        Returns:
            A source observation with the actual collection timestamp.
        """
        reads.append(path)
        return (mapping(100, captured_at=captured),)

    monkeypatch.setattr(peri_scribe.publication, "snapshot_mappings", measure)
    initial = peri_scribe.publication.collect(tmp_path)
    assert peri_scribe.publication.collect(tmp_path) == initial
    assert reads == [first]
    second = sources / "000002,lastEdit=2.gpkg"
    second.write_bytes(b"second")
    updated = peri_scribe.publication.collect(tmp_path)
    assert reads == [first, second]
    assert set(updated.files) == {first.name, second.name}
    # External-only updates reuse measurements; lost cache rows are reconstructed.
    evacuation = peri_scribe.sources.external_sources.output_path(
        tmp_path,
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    )
    evacuation.write_bytes(b"evacuations")
    assert peri_scribe.publication.collect(tmp_path).evacuations is not None
    assert reads == [first, second]
    broken = updated.model_copy(
        update={"mappings": {first.name: updated.mappings[first.name]}},
    )
    peri_scribe.publication.write_state(
        peri_scribe.publication.collection_path(tmp_path),
        broken,
    )
    peri_scribe.publication.collect(tmp_path)
    assert reads == [first, second, second]
    first.write_bytes(b"replaced")
    peri_scribe.publication.collect(tmp_path)
    assert reads[-1] == first
    second.unlink()
    assert set(peri_scribe.publication.collect(tmp_path).files) == {first.name}


def test_published_baseline_uses_raw_source_for_latest_displayed_history() -> None:
    first, latest, excluded, unnamed = (
        mapping(100),
        mapping(130, serial=2),
        mapping(10, serial=3, identifiers=("tiny",)),
        mapping(40, serial=4, identifiers=()),
    )
    rows = geopandas.GeoDataFrame({
        "fire_identifier": ["a", "a", "tiny", None],
        "fire_name": ["Example", "Example", "Tiny", "Unnamed"],
        "fire_aliases": [None, "Alias", "tiny", None],
        "source_file": [
            item.source_file for item in (first, latest, excluded, unnamed)
        ],
        "source_objectid": [1, 2, 3, 4],
    })
    index = peri_scribe.models.FireIndex(
        version="test",
        fires=[
            peri_scribe.models.FireIndexEntry(
                name="Example",
                identifier="a",
                status="active",
                paths=[],
            ),
            peri_scribe.models.FireIndexEntry(
                name="Unnamed",
                status="active",
                paths=[],
            ),
        ],
    )
    fires = peri_scribe.publication.published_fires(
        collection(first, latest, excluded, unnamed),
        rows,
        index,
    )
    assert fires["id:a"].mapping == latest
    assert fires["id:a"].identifiers == ("a", "alias")
    assert fires["id:tiny"].mapping is None
    assert fires["name:Unnamed"].mapping == unnamed
    assert fires["name:Unnamed"].identifiers == ()
    with pytest.raises(ValueError, match="Cannot identify published mapping source"):
        peri_scribe.publication.published_fires(collection(), rows, index)
