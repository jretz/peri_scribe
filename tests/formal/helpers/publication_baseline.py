"""Complete publication collections paired with the compiled ownership specification."""

from __future__ import annotations

import dataclasses
import datetime
import itertools
import typing

import geopandas
import pandas as pd
import pytest

import peri_scribe.models
import peri_scribe.publication


if typing.TYPE_CHECKING:
    import collections.abc

ORIGIN = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)


def optional(value: int | None) -> str:
    """Preserve absence separately from identifier zero in oracle transport.

    Args:
        value: A raw identifier or object key.

    Returns:
        The oracle's optional natural encoding.
    """
    return "n" if value is None else str(value)


def identifiers(values: tuple[int, ...]) -> str:
    """Keep alias lists distinct from names and object keys.

    Args:
        values: Independently supplied identity labels.

    Returns:
        A colon-separated oracle field, or the empty-list marker.
    """
    return ":".join(map(str, values)) or "n"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Source:
    """Raw measurements keep unique evidence identities despite repeated file keys."""

    file: int
    object_id: int | None
    identity: int
    aliases: tuple[int, ...] = ()

    def command(self) -> str:
        """Encode provenance and aliases without performing a source join.

        Returns:
            One raw-source field for the Lean oracle.
        """
        return (
            f"{self.file},{optional(self.object_id)},{self.identity},"
            f"{identifiers(self.aliases)}"
        )

    def production(self) -> peri_scribe.publication.Mapping:
        """Make source values distinguishable from derived displayed metadata.

        Returns:
            A real immutable mapping with distinct area, time, and provenance.
        """
        return peri_scribe.publication.Mapping(
            source_file=f"{self.file}.gpkg",
            object_id=self.object_id,
            identifiers=tuple(f"i{value}" for value in self.aliases),
            name=f"Source {self.identity}",
            observed_at=ORIGIN - datetime.timedelta(hours=self.identity),
            captured_at=ORIGIN,
            serial=100 - self.identity,
            shape=f"raw-shape-{self.identity}",
            area_square_meters=1000 + self.identity,
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Row:
    """Displayed history supplies owner and source keys independently of raw aliases."""

    identifier: int | None
    name: int
    file: int
    object_id: int | None
    aliases: tuple[int, ...] = ()

    def command(self) -> str:
        """Pass the displayed row to the oracle before resolving its raw source.

        Returns:
            One displayed-history field.
        """
        return (
            f"{optional(self.identifier)},{self.name},{self.file},"
            f"{optional(self.object_id)},{identifiers(self.aliases)}"
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Entry:
    """The actual output index supplies inclusion through aliases or anonymous names."""

    identifier: int | None
    name: int
    aliases: tuple[int, ...] = ()

    def command(self) -> str:
        """Keep index entries explicit instead of supplying a precomputed inclusion.

        Returns:
            One index field for the oracle.
        """
        return f"{optional(self.identifier)},{self.name},{identifiers(self.aliases)}"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """The collection, displayed stream, and output index describe one publication."""

    sources: tuple[Source, ...]
    rows: tuple[Row, ...]
    entries: tuple[Entry, ...]

    def command(self) -> str:
        """Send raw inputs to the same fold whose invariants Lean checks.

        Returns:
            The complete publication-baseline command.
        """
        return "|".join([
            "baseline",
            " ".join(entry.command() for entry in self.entries),
            " ".join(source.command() for source in self.sources),
            " ".join(row.command() for row in self.rows),
        ])

    def collection(self) -> peri_scribe.publication.Collection:
        """Preserve multiple raw objects and duplicates within their actual files.

        Returns:
            The frozen source inventory used by the production join.
        """
        return peri_scribe.publication.Collection(
            mappings={
                f"{file}.gpkg": tuple(
                    source.production()
                    for source in self.sources
                    if source.file == file
                )
                for file in sorted(
                    {source.file for source in self.sources},
                    reverse=True,
                )
            },
        )

    def frame(self) -> geopandas.GeoDataFrame:
        """Vary raw spelling and DataFrame labels without changing declared row order.

        Returns:
            Actual history rows with repeated labels and normalized identity variants.
        """
        return geopandas.GeoDataFrame(
            {
                "fire_identifier": [
                    pd.NA if row.identifier is None else f" {{I{row.identifier}}} "
                    for row in self.rows
                ],
                "fire_name": [f"Fire {row.name}" for row in self.rows],
                "fire_aliases": [
                    ",".join(
                        f" {{I{value}}} " for value in (*row.aliases, *row.aliases)
                    )
                    if row.aliases
                    else pd.NA
                    for row in self.rows
                ],
                "source_file": [f"{row.file}.gpkg" for row in self.rows],
                "source_objectid": [
                    None if row.object_id is None else str(row.object_id)
                    for row in self.rows
                ],
            },
            index=[5] * len(self.rows),
        )

    def index(self) -> peri_scribe.models.FireIndex:
        """Use real validated output entries with explicit names and aliases.

        Returns:
            The index whose inclusion relation the model also evaluates.
        """
        return peri_scribe.models.FireIndex(
            version="formal",
            fires=[
                peri_scribe.models.FireIndexEntry(
                    identifier=None
                    if entry.identifier is None
                    else f"i{entry.identifier}",
                    name=f"Fire {entry.name}",
                    aliases=[f"i{value}" for value in entry.aliases],
                    status="active",
                    paths=[],
                )
                for entry in self.entries
            ],
        )


def cases() -> list[Case]:
    """Cross repeated owners, alias accumulation, namesakes, and index membership.

    Returns:
        Exhaustive short row streams plus permutations and ambiguous-source cases.
    """
    sources = (
        Source(file=0, object_id=0, identity=0, aliases=(0,)),
        Source(file=0, object_id=1, identity=1, aliases=(1,)),
        Source(file=1, object_id=0, identity=2, aliases=(2,)),
        Source(file=1, object_id=None, identity=3),
        Source(file=2, object_id=2, identity=4, aliases=(3,)),
    )
    rows = (
        Row(identifier=0, name=0, file=0, object_id=0),
        Row(identifier=0, name=1, file=0, object_id=1, aliases=(2,)),
        Row(identifier=0, name=0, file=1, object_id=0, aliases=(3,)),
        Row(identifier=1, name=0, file=1, object_id=None),
        Row(identifier=None, name=0, file=1, object_id=None),
        Row(identifier=None, name=0, file=2, object_id=2, aliases=(1,)),
        Row(identifier=None, name=1, file=1, object_id=None, aliases=(2,)),
        Row(identifier=2, name=2, file=2, object_id=2, aliases=(0,)),
    )
    indexes = (
        (),
        (Entry(identifier=0, name=9),),
        (Entry(identifier=3, name=9, aliases=(2,)),),
        (Entry(identifier=None, name=0),),
        (Entry(identifier=3, name=0),),
        (Entry(identifier=None, name=1, aliases=(1,)),),
        (
            Entry(identifier=0, name=0, aliases=(2,)),
            Entry(identifier=1, name=1, aliases=(2,)),
        ),
    )
    histories = [
        history
        for length in range(4)
        for history in itertools.product(rows, repeat=length)
    ]
    histories.extend(itertools.permutations((rows[0], rows[1], rows[3], rows[4])))
    result = [
        Case(sources=sources, rows=history, entries=index)
        for history, index in itertools.product(histories, indexes)
    ]
    for source in sources:
        selected = next(
            row
            for row in rows
            if (
                row.file,
                row.object_id,
            )
            == (source.file, source.object_id)
        )
        for inventory in [
            tuple(value for value in sources if value != source),
            (*sources, dataclasses.replace(source, identity=source.identity + 10)),
        ]:
            for history in [(selected,), (rows[-1], selected), (selected, rows[-1])]:
                result.extend(
                    Case(sources=inventory, rows=history, entries=index)
                    for index in indexes
                )
    return result


def encode_result(
    fires: collections.abc.Mapping[str, peri_scribe.publication.PublishedFire],
) -> tuple[int, ...]:
    """Encode actual dictionary order and source identity without recomputing ownership.

    Args:
        fires: The real publication result.

    Returns:
        Complete owner, name, source, and alias vectors in insertion order.
    """
    values = [len(fires)]
    for key, fire in fires.items():
        owner = (
            (0, int(key.removeprefix("id:i")))
            if key.startswith("id:")
            else (1, int(key.removeprefix("name:Fire ")))
        )
        values.extend([
            *owner,
            int(fire.name.removeprefix("Fire ")),
            -1
            if fire.mapping is None
            else int(fire.mapping.name.removeprefix("Source ")),
            len(fire.identifiers),
            *(int(value.removeprefix("i")) for value in fire.identifiers),
        ])
    return tuple(values)


def check(case: Case, expected: tuple[int, ...]) -> None:
    """Require the complete real collection to agree with the checked result.

    Args:
        case: Independent collection, row-order, and index inputs.
        expected: The actual compiled oracle response.
    """
    collection, frame, index = case.collection(), case.frame(), case.index()
    if expected == (-1,):
        with pytest.raises(
            ValueError,
            match="Cannot identify published mapping source",
        ):
            peri_scribe.publication.published_fires(collection, frame, index)
        return
    actual = peri_scribe.publication.published_fires(collection, frame, index)
    assert encode_result(actual) == expected, case
    sources = {source.identity: source.production() for source in case.sources}
    for fire in actual.values():
        if fire.mapping is not None:
            identity = int(fire.mapping.name.removeprefix("Source "))
            assert fire.mapping == sources[identity]
