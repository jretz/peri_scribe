"""Bind publication alias components, candidates, and comparisons to real models."""

import dataclasses
import datetime
import itertools

import geopandas
import numpy as np

import peri_scribe.models
import peri_scribe.publication
import tests.formal.helpers.generation
import tests.helpers.factories.peri_scribe.publication
from measurement_units import units


BASE = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
ORDER_TIE_RANKS = 4


@dataclasses.dataclass(frozen=True, kw_only=True)
class Mapping:
    """Independent mapping dates, geometry, and area expose policy choices."""

    identity: int
    identifiers: tuple[int, ...] = (0,)
    order: int = 4
    captured: int = 0
    shape: int = 0
    area: int | None = 100
    collapsed: bool = False

    def command(self) -> str:
        """Encode a mapping without evaluating candidate or comparison policy.

        Returns:
            The formal mapping vector with canonical identifier ranks.
        """
        return ",".join(
            map(
                str,
                (
                    self.identity,
                    sum(1 << value for value in self.identifiers),
                    self.order,
                    self.captured,
                    self.shape,
                    -1 if self.area is None else self.area,
                    int(self.collapsed),
                ),
            ),
        )

    def production(self) -> peri_scribe.publication.Mapping:
        """Lexicographic timestamp, serial, and object fields realize the abstract rank.

        Returns:
            A real validated raw mapping with square-meter measurements.
        """
        return peri_scribe.publication.Mapping(
            source_file=f"{self.identity}.gpkg",
            object_id=1 + self.order % 2,
            identifiers=tuple(f"i{value}" for value in self.identifiers),
            name=str(self.identity),
            observed_at=None
            if self.order < ORDER_TIE_RANKS
            else BASE + datetime.timedelta(seconds=self.order // 4),
            captured_at=BASE + datetime.timedelta(seconds=self.captured),
            serial=self.order % 4 // 2,
            shape=str(self.shape),
            area_square_meters=self.area,
            collapsed=self.collapsed,
        )


def histories() -> list[list[Mapping]]:
    """Alias chains and shape boundaries exercise repeated capture propagation.

    Returns:
        Mapping streams including empty identities and order permutations.
    """
    bridge = [
        Mapping(identity=0, identifiers=(0,), captured=5),
        Mapping(identity=1, identifiers=(1,), captured=1),
        Mapping(identity=2, identifiers=(0, 2), captured=3),
        Mapping(identity=3, identifiers=(1, 2), captured=7),
        Mapping(identity=4, identifiers=(0,), captured=0, shape=1),
        Mapping(identity=5, identifiers=(), captured=2),
    ]
    result = [
        [],
        *[list(values) for values in itertools.permutations(bridge[:4])],
        bridge,
    ]
    generator = np.random.default_rng(20260928)
    choose = tests.formal.helpers.generation.choose
    identifiers = ((), (0,), (1,), (2,), (0, 1), (0, 2), (1, 2), (0, 1, 2))
    result.extend(
        [
            Mapping(
                identity=index,
                identifiers=choose(generator, identifiers),
                order=int(generator.integers(12)),
                captured=int(generator.integers(8)),
                shape=int(generator.integers(3)),
                area=choose(generator, (None, 0, 1, 25, 100, 125)),
                collapsed=choose(generator, (False, True)),
            )
            for index in range(int(generator.integers(1, 9)))
        ]
        for _ in range(700)
    )
    return result


def publication(
    owners: tuple[tuple[int, int], ...],
) -> peri_scribe.publication.Publication:
    """A validated unique alias relation supplies the candidate fold's initial state.

    Args:
        owners: Identifier ranks and their existing published fire keys.

    Returns:
        A real checkpoint with independently named published identities.
    """
    return peri_scribe.publication.Publication(
        created_at=BASE,
        output=tests.helpers.factories.peri_scribe.publication.STAMP,
        files={},
        fires={
            f"id:owner{key}": peri_scribe.publication.PublishedFire(
                identifiers=tuple(
                    f"i{identifier}" for identifier, owner in owners if owner == key
                ),
                name=f"Owner {key}",
                mapping=Mapping(identity=20 + key).production(),
            )
            for key in dict.fromkeys(owner for _, owner in owners)
        },
    )


def candidate_result(
    values: list[Mapping],
    owners: tuple[tuple[int, int], ...],
) -> tuple[int, ...]:
    """Read candidate identities and verify the actual published baseline association.

    Args:
        values: Raw unpublished mappings.
        owners: The checkpoint's validated identifier ownership.

    Returns:
        Ordered key and source-row identities, or -1 for conservative uncertainty.
    """
    published = publication(owners)
    result = peri_scribe.publication.candidate_fires(
        [value.production() for value in values],
        published,
    )
    if result is None:
        return (-1,)
    flattened = []
    for key, (mapping, baseline) in result.items():
        assert baseline == published.fires.get(key)
        rank = int(key.removeprefix("id:owner").removeprefix("id:i"))
        flattened.extend((rank, int(mapping.source_file.split(".")[0])))
    return tuple(flattened)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Comparison:
    """An optional displayed raw mapping supplies a baseline for signed area change."""

    current: Mapping
    baseline: Mapping | None

    def command(self) -> str:
        """Expose raw measurements and order without calculating eligible changes.

        Returns:
            A current-to-baseline vector accepted by the executable proof definitions.
        """
        baseline = "none" if self.baseline is None else self.baseline.command()
        return f"{self.current.command()}:{baseline}"


def comparisons() -> list[list[Comparison]]:
    """Include shrinkage, excluded baselines, stale uncertainty, and ties across fires.

    Returns:
        Complete candidate sets with boundary and reproducibly generated measurements.
    """
    result: list[list[Comparison]] = [[]]
    for current, baseline, order in itertools.product(
        (None, 0, 1, 24, 25, 26, 75, 100, 125, 126),
        (None, 0, 1, 25, 100, 125),
        (3, 4, 5),
    ):
        result.append([
            Comparison(
                current=Mapping(identity=0, area=current, order=order),
                baseline=Mapping(identity=10, area=baseline),
            ),
            Comparison(
                current=Mapping(identity=1, area=75),
                baseline=Mapping(identity=11),
            ),
        ])
    generator = np.random.default_rng(20260929)
    choose = tests.formal.helpers.generation.choose
    result.extend(
        [
            Comparison(
                current=Mapping(
                    identity=index,
                    area=choose(generator, (None, 0, 1, 25, 100, 125, 1000)),
                    order=int(generator.integers(12)),
                ),
                baseline=None
                if generator.integers(3) == 0
                else Mapping(
                    identity=10 + index,
                    area=choose(generator, (None, 0, 1, 25, 100, 125, 1000)),
                    order=int(generator.integers(12)),
                ),
            )
            for index in range(int(generator.integers(1, 6)))
        ]
        for _ in range(600)
    )
    return result


def comparison_result(values: list[Comparison], threshold: int) -> tuple[int, ...]:
    """Exercise the production comparison including units, uncertainty, and tie order.

    Args:
        values: Candidate measurements and optional displayed baselines.
        threshold: The integral absolute square-meter publication threshold.

    Returns:
        Proceed, uncertainty, signed square-meter change, and selected fire identity.
    """
    result = peri_scribe.publication.mapping_decision(
        {
            str(value.current.identity): (
                value.current.production(),
                None
                if value.baseline is None
                else peri_scribe.publication.PublishedFire(
                    identifiers=("baseline",),
                    name="Baseline",
                    mapping=value.baseline.production(),
                ),
            )
            for value in values
        },
        peri_scribe.publication.Threshold(
            area=threshold * units.Unit("meters ** 2"),
            interval=datetime.timedelta(minutes=5),
        ),
    )
    return (
        int(result.proceed),
        int(result.reason == peri_scribe.publication.Reason.UNCERTAIN_MAPPING),
        round(result.change.m_as("meters ** 2")),
        -1 if result.fire is None else int(result.fire),
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class RawSource:
    """Raw row addresses are independent of fire identities and measurements."""

    file: int
    object_id: int
    mapping: Mapping

    def command(self) -> str:
        """Keep source-row association independent of any derived fire geometry.

        Returns:
            The exact file and object key followed by its raw mapping vector.
        """
        return f"{self.file}:{self.object_id}:{self.mapping.command()}"


def raw_sources() -> list[list[RawSource]]:
    """Exhaustive small inventories include absent, unique, and duplicate source keys.

    Returns:
        Raw records with independently distinguishable mapping measurements.
    """
    keys = tuple(itertools.product(range(2), repeat=2))
    return [
        [
            RawSource(
                file=file,
                object_id=object_id,
                mapping=Mapping(identity=index, area=100 + index, identifiers=(2,)),
            )
            for index, (file, object_id) in enumerate(selected)
        ]
        for size in range(4)
        for selected in itertools.product(keys, repeat=size)
    ]


def published_baseline(
    rows: list[RawSource],
    file: int,
    object_id: int,
    *,
    included: bool,
) -> peri_scribe.publication.PublishedFire:
    """Use the real collection and displayed-history join to recover a raw baseline.

    Args:
        rows: The downloaded raw mapping inventory.
        file: The source snapshot referenced by the displayed history.
        object_id: The source row referenced by the displayed history.
        included: Whether the KMZ index includes this fire.

    Returns:
        The derived published fire with its raw mapping or excluded baseline.
    """
    collection = peri_scribe.publication.Collection(
        mappings={
            f"{source}.gpkg": tuple(
                row.mapping.production().model_copy(
                    update={
                        "source_file": f"{source}.gpkg",
                        "object_id": row.object_id,
                    },
                )
                for row in rows
                if row.file == source
            )
            for source in (0, 1)
        },
    )
    perimeters = geopandas.GeoDataFrame({
        "fire_identifier": ["i0"],
        "fire_aliases": ["i1"],
        "fire_name": ["Displayed"],
        "source_file": [f"{file}.gpkg"],
        "source_objectid": [str(object_id) if file else float(object_id)],
    })
    index = peri_scribe.models.FireIndex(
        version="formal",
        fires=[
            peri_scribe.models.FireIndexEntry(
                name="Displayed",
                identifier="i0" if file else "i1",
                status="active",
                paths=[],
            ),
        ]
        if included
        else [],
    )
    return peri_scribe.publication.published_fires(collection, perimeters, index)[
        "id:i0"
    ]
