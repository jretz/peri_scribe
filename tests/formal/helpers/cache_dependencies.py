"""Compare declared cache dependencies with real persistent hits and fresh products."""

from __future__ import annotations

import dataclasses
import datetime
import functools
import pathlib
import typing

import numpy as np
import pyproj
import pytest
import shapely

import kml_io.fragments
import kml_io.geometry
import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.fires.buffering
import peri_scribe.fires.spatial_products
import peri_scribe.kml.fire_data
import peri_scribe.kml.plot_rendering
import peri_scribe.perimeters.progression
import peri_scribe.presentation.prepared_cache
import peri_scribe.presentation.selection
import peri_scribe.presentation.text
import spatial_data.cache_values
import spatial_data.product_cache
import spatial_data.reference
import svg_charts.models
import svg_charts.time_series
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.peri_scribe.kml.plot_rendering
import tests.helpers.factories.peri_scribe.presentation.fire_data
import tests.helpers.factories.spatial_data.point_store
from measurement_units import units


if typing.TYPE_CHECKING:
    import geopandas


@dataclasses.dataclass(frozen=True, kw_only=True)
class Contract:
    """Declare semantic dependencies independently of the implementation's keys."""

    namespace: str
    consumed: tuple[str, ...]
    wrappers: tuple[str, ...] = ()

    def command(self, change: str) -> str:
        """Project a single input mutation into the proved dependency algebra.

        Args:
            change: One declared content dependency or deliberately live wrapper.

        Returns:
            An executable Lean request over all fields of this contract.
        """
        fields = (*self.consumed, *self.wrappers)
        required = " ".join(map(str, range(len(self.consumed))))
        before = " ".join("0" for _field in fields)
        after = " ".join("1" if field == change else "0" for field in fields)
        assert change in fields
        return f"{required}|{required}|{before}|{after}"


CHART = Contract(
    namespace=peri_scribe.kml.plot_rendering.PLOT_NAMESPACE,
    consumed=(
        "value",
        "time",
        "style",
        "label",
        "color",
        "dashed_label",
        "axis",
        "order",
        "settings",
        "timezone",
    ),
    wrappers=("filename", "bundle"),
)
HISTORY = Contract(
    namespace="prepared_histories",
    consumed=("value", "order", "schema", "crs", "geometry", "alias", "policy"),
    wrappers=("index",),
)
DESCRIPTION = Contract(
    namespace="fire_descriptions",
    consumed=("metadata", "perimeter", "point", "history", "geometry"),
    wrappers=("note",),
)
BUFFER = Contract(
    namespace=peri_scribe.fires.spatial_products.BUFFER_NAMESPACE,
    consumed=("geometry", "distance", "projection", "runtime"),
)
BUILDINGS = Contract(
    namespace=peri_scribe.fires.spatial_products.COUNT_NAMESPACE,
    consumed=("geometry", "dataset", "runtime"),
)
BOUNDARY = Contract(
    namespace=kml_io.fragments.NAMESPACE,
    consumed=("geometry", "order", "srid", "precision"),
)
RINGS = Contract(
    namespace=peri_scribe.kml.fire_data.RING_AREA_NAMESPACE,
    consumed=("geometry", "order"),
    wrappers=("time",),
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Access:
    """Retain the actual context, structured key identity, and authenticated hit."""

    context: str
    key: str
    hit: bool


def record_reads(
    monkeypatch: pytest.MonkeyPatch,
    namespace: str,
) -> list[Access]:
    """Observe production lookups without replacing their cache behavior.

    Args:
        monkeypatch: The scoped observer's lifetime.
        namespace: The product whose key contract is under examination.

    Returns:
        The append-only observations produced by real SQLite lookups.
    """
    accesses: list[Access] = []
    original = spatial_data.product_cache.get

    def get(product: str, key: str) -> bytes | None:
        """Retain the selected product's authenticated lookup result.

        Args:
            product: The actual product namespace.
            key: Its actual input fingerprint.

        Returns:
            The original cache result unchanged.
        """
        result = original(product, key)
        store = spatial_data.product_cache.CURRENT.get()
        if product == namespace and store is not None:
            accesses.append(
                Access(context=store.context, key=key, hit=result is not None),
            )
        return result

    monkeypatch.setattr(spatial_data.product_cache, "get", get)
    return accesses


def check_transition(
    directory: pathlib.Path,
    contract: Contract,
    change: str,
    before: typing.Callable[[], bytes],
    after: typing.Callable[[], bytes],
) -> None:
    """Require Lean's invalidation decision and exact fresh output on a real cache.

    Each call owns a fresh execution scope so memoized input ownership stays valid.

    Args:
        directory: Isolated storage for one dependency mutation.
        contract: Independently declared content dependencies and live wrappers.
        change: The single field changed by the second computation.
        before: Baseline computation with real deterministic product generation.
        after: Changed computation with real deterministic product generation.
    """
    (expected,) = tests.formal.helpers.oracle.evaluate(
        [contract.command(change)],
        executable="oracleCache",
    )
    complete, same_key, same_dependencies = expected
    assert complete == 1
    assert same_key == same_dependencies
    path = directory / "products.sqlite"
    with pytest.MonkeyPatch.context() as monkeypatch:
        accesses = record_reads(monkeypatch, contract.namespace)
        with (
            peri_scribe.execution.sharing(),
            spatial_data.product_cache.scope(path, "runtime"),
        ):
            baseline = before()
        (cold,) = accesses
        assert not cold.hit
        accesses.clear()
        with (
            peri_scribe.execution.sharing(),
            spatial_data.product_cache.scope(path, "runtime"),
        ):
            assert before() == baseline
        (warm,) = accesses
        assert warm.hit
        assert (warm.context, warm.key) == (cold.context, cold.key)
        accesses.clear()
        with (
            peri_scribe.execution.sharing(),
            spatial_data.product_cache.scope(
                path,
                "changed-runtime" if change == "runtime" else "runtime",
            ),
        ):
            changed = after()
        (actual,) = accesses
        assert actual.hit == bool(same_key)
        assert ((actual.context, actual.key) == (cold.context, cold.key)) == bool(
            same_key,
        )
        with peri_scribe.execution.sharing():
            fresh = after()
        assert changed == fresh


def chart(change: str) -> bytes:
    """Render real SVG bytes while varying exactly one drawing or wrapper input.

    Args:
        change: The requested mutation, or an empty string for baseline input.

    Returns:
        Exact current filename and SVG bytes in canonical serialization.
    """
    request = tests.helpers.factories.peri_scribe.kml.plot_rendering.plot_request()
    series = request.series[0]
    other = dataclasses.replace(series, label="Other")
    request = dataclasses.replace(request, series=(series, other))
    match change:
        case "value":
            point = dataclasses.replace(series.points[0], value=3.0)
            series = dataclasses.replace(series, points=(point, series.points[1]))
            request = dataclasses.replace(request, series=(series, other))
        case "time":
            point = dataclasses.replace(
                series.points[0],
                observation_time=series.points[0].observation_time
                - datetime.timedelta(days=1),
            )
            series = dataclasses.replace(series, points=(point, series.points[1]))
            request = dataclasses.replace(request, series=(series, other))
        case "label":
            request = dataclasses.replace(
                request,
                series=(dataclasses.replace(series, label="Changed"), other),
            )
        case "style":
            point = dataclasses.replace(
                series.points[1],
                style=svg_charts.models.StrokeStyle.DASHED,
            )
            series = dataclasses.replace(series, points=(series.points[0], point))
            request = dataclasses.replace(request, series=(series, other))
        case "color":
            request = dataclasses.replace(
                request,
                series=(dataclasses.replace(series, color="#112233"), other),
            )
        case "dashed_label":
            request = dataclasses.replace(
                request,
                series=(dataclasses.replace(series, dashed_label="Estimated"), other),
            )
        case "axis":
            request = dataclasses.replace(request, y_axis_label="Changed")
        case "order":
            request = dataclasses.replace(request, series=(other, series))
        case "filename":
            request = dataclasses.replace(request, filename_prefix="new-owner")
    with pytest.MonkeyPatch.context() as monkeypatch:
        if change == "settings":
            monkeypatch.setattr(
                svg_charts.time_series,
                "CHART_WIDTH",
                999 * units.pixels,
            )
        monkeypatch.setenv("TZ", "EST5EDT" if change == "timezone" else "UTC0")
        result = peri_scribe.kml.plot_rendering.render_plot_request(request)
    return spatial_data.cache_values.dumps((result.filename, result.content))


def evidence(change: str) -> tuple[geopandas.GeoDataFrame, geopandas.GeoDataFrame]:
    """Keep complete history schemas, chronology, geometry, and metadata in scope.

    Args:
        change: The requested row mutation, or an empty string for baseline input.

    Returns:
        Perimeter and point frames belonging to one canonical fire.
    """
    factory = tests.helpers.factories.peri_scribe.presentation.fire_data
    perimeters = factory.description_perimeter_frame()
    points = factory.description_point_frame()
    match change:
        case "value":
            perimeters.loc[0, "estimated_cost_to_date"] = 9_000.0
        case "order":
            perimeters = perimeters.iloc[::-1]
        case "schema":
            perimeters["percent_contained"] = perimeters["percent_contained"].astype(
                "int64",
            )
        case "crs":
            perimeters.set_crs("EPSG:3857", allow_override=True, inplace=True)
        case "geometry":
            perimeters.geometry = perimeters.geometry.translate(0.01)
        case "index":
            perimeters.index = [42, 42]
        case "perimeter":
            perimeters.loc[1, "mission"] = "CHANGED"
        case "point":
            points.loc[0, "source_attributes"] = '{"POOJurisdictionalUnit":"CHANGED"}'
    return perimeters, points


def history(change: str) -> bytes:
    """Serialize the complete real prepared history, including every update field.

    Args:
        change: A consumed evidence/policy field or ignored DataFrame index labels.

    Returns:
        Exact canonical identity and complete serialized prepared history.
    """
    perimeters, points = evidence(change)
    with pytest.MonkeyPatch.context() as monkeypatch:
        if change == "policy":
            policy = peri_scribe.areas.DEFAULT_POLICY
            monkeypatch.setattr(
                peri_scribe.areas,
                "DEFAULT_POLICY",
                dataclasses.replace(policy, stale_after=datetime.timedelta(days=1)),
            )
        histories = peri_scribe.presentation.selection.prepare_histories(
            perimeters,
            points,
            aliases={"id-bug": "canonical"} if change == "alias" else None,
        )
    return spatial_data.cache_values.dumps(
        tuple(
            (identity, peri_scribe.presentation.prepared_cache.history_bytes(value))
            for identity, value in sorted(histories.items())
        ),
    )


def description(change: str) -> bytes:
    """Check complete histories plus latest row facts and live score explanations.

    Args:
        change: One source of description content or the current score explanation.

    Returns:
        The complete description with original units and the current note.
    """
    perimeters, points = evidence(change)
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Changed" if change == "metadata" else "Bug",
        "active",
        identifier="id-bug",
    )
    prepared = peri_scribe.areas.prepare_history(perimeters, points)
    if change == "history":
        prepared = dataclasses.replace(
            prepared,
            updates=tuple(
                dataclasses.replace(
                    update,
                    measurements={
                        **update.measurements,
                        "estimated_cost_to_date": 9_000,
                    },
                )
                for update in prepared.updates
            ),
        )
    result = peri_scribe.presentation.text.fire_description(
        entry,
        perimeters,
        points,
        "current" if change == "note" else "baseline",
        history=prepared,
    )
    return peri_scribe.presentation.prepared_cache.description_bytes(result)


def buffer(change: str) -> bytes:
    """Compare exact projected buffer geometries through the real spatial cache.

    Args:
        change: Geometry, buffer distance, projection, runtime, or baseline.

    Returns:
        Exact ordered WKB including its SRID.
    """
    geometry = shapely.Point(-121 if change == "geometry" else -120, 40)
    with pytest.MonkeyPatch.context() as monkeypatch:
        if change == "distance":
            monkeypatch.setattr(
                peri_scribe.fires.buffering,
                "BUILDING_BUFFER",
                2 * units.miles,
            )
        if change == "projection":
            monkeypatch.setattr(
                spatial_data.reference,
                "WEB_MERCATOR_SPATIAL_REFERENCE",
                pyproj.CRS.from_epsg(3310),
            )
        result = peri_scribe.fires.spatial_products.buffered_geometries([geometry])
    return spatial_data.cache_values.dumps(
        tuple(shapely.to_wkb(result, include_srid=True)),
    )


def buildings(path: pathlib.Path, change: str) -> bytes:
    """Query real point databases, including replacement with changed dataset bytes.

    Args:
        path: The building dataset for this computation.
        change: A query geometry mutation or unchanged query.

    Returns:
        Exact counts from real spatial queries.
    """
    geometry = shapely.box(0, 0, 3 if change == "geometry" else 2, 3)
    return spatial_data.cache_values.dumps(
        tuple(
            peri_scribe.fires.spatial_products.building_counts([geometry], path),
        ),
    )


def building_transition(directory: pathlib.Path, change: str) -> None:
    """Use real datasets with different contents under the same product context.

    Args:
        directory: Isolated input and cache storage.
        change: Dataset, geometry, or runtime mutation.
    """
    before = directory / "buildings.sqlite"
    after = directory / "replacement.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([[1, 1], [2.5, 1]]),
        before,
    )
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([[1, 1], [1.5, 1], [2.5, 1]]),
        after,
    )
    check_transition(
        directory,
        BUILDINGS,
        change,
        functools.partial(buildings, before, ""),
        functools.partial(replaced_buildings, before, after, change),
    )


def replaced_buildings(
    path: pathlib.Path,
    replacement: pathlib.Path,
    change: str,
) -> bytes:
    """Replace authoritative bytes at the original path before the changed query.

    Args:
        path: The unchanged authoritative dataset path used by every computation.
        replacement: Prepared new bytes, consumed only on the first changed call.
        change: Dataset, geometry, or runtime mutation.

    Returns:
        Exact current counts, preserving the same replacement for fresh verification.
    """
    if change == "dataset" and replacement.exists():
        replacement.replace(path)
    return buildings(path, change)


def boundary(change: str) -> bytes:
    """Render actual coordinate fragments with matching precision and geometry.

    Args:
        change: Exact geometry, component order, SRID, or coordinate precision.

    Returns:
        Canonical serialized boundary strings from the real formatter.
    """
    first = shapely.box(1.123456, 1, 2, 2)
    second = shapely.box(3, 3, 4, 4)
    geometry = shapely.MultiPolygon([first, second])
    if change == "geometry":
        geometry = shapely.MultiPolygon([shapely.box(1, 1, 2.5, 2), second])
    if change == "order":
        geometry = shapely.MultiPolygon([second, first])
    if change == "srid":
        geometry = shapely.set_srid(geometry, 4326)
    with pytest.MonkeyPatch.context() as monkeypatch:
        if change == "precision":
            monkeypatch.setattr(kml_io.geometry, "COORDINATE_DECIMALS", 3)
        result = kml_io.fragments.BoundaryCache().boundaries(
            geometry,
            kml_io.geometry.COORDINATE_DECIMALS,
            kml_io.geometry.geometry_boundaries,
        )
    return spatial_data.cache_values.dumps(result)


def rings(change: str) -> bytes:
    """Measure the exact ordered progression while leaving observation labels live.

    Args:
        change: A ring shape, its sequence order, or an irrelevant date label.

    Returns:
        Exact ordered added-area quantities without rounding their magnitudes.
    """
    time = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
    first = peri_scribe.perimeters.progression.Ring(
        geometry=shapely.box(0, 0, 2 if change == "geometry" else 1, 1),
        observation_time=time + datetime.timedelta(days=change == "time"),
    )
    second = peri_scribe.perimeters.progression.Ring(
        geometry=shapely.box(0, 0, 3, 3),
        observation_time=time,
    )
    sequence = (second, first) if change == "order" else (first, second)
    return spatial_data.cache_values.dumps(
        peri_scribe.kml.fire_data.added_areas_for_rings(sequence),
    )
