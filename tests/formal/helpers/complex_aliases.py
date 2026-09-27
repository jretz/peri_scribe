"""Connect incomplete source rows to the proved ownership policy through real files."""

from __future__ import annotations

import dataclasses
import pathlib

import geopandas
import shapely

import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds
import tests.formal.helpers.complex_ownership


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Raw columns and independent aliases describe the same source update."""

    raw_identifiers: tuple[str | None, str]
    identifiers: tuple[int, ...]
    parent: int | None
    location: bool

    @property
    def history(self) -> tests.formal.helpers.complex_ownership.History:
        """Retain every supplied alias in the evidence sent to Lean.

        Returns:
            The initial assignment and each alias of its later correction.
        """
        return (
            tests.formal.helpers.complex_ownership.Evidence(
                child=0,
                parent=1,
                location=self.location,
            ),
            *(
                tests.formal.helpers.complex_ownership.Evidence(
                    child=identifier,
                    parent=self.parent,
                    time=2,
                    location=self.location,
                )
                for identifier in self.identifiers
            ),
        )


def cases(*, location: bool) -> list[Case]:
    """Identifiers remain usable when earlier columns are absent or unrelated.

    Args:
        location: Whether the row belongs to the incident location feed.

    Returns:
        Releases and assignments with missing, unknown, and duplicated primary aliases.
    """
    return [
        Case(
            raw_identifiers=raw_identifiers,
            identifiers=identifiers,
            parent=parent,
            location=location,
        )
        for parent in (None, 2)
        for raw_identifiers, identifiers in (
            ((None, "identifier-3"), (3,)),
            (("identifier-6", "identifier-3"), (6, 3)),
            ((" {IDENTIFIER-3} ", "identifier-3"), (3, 3)),
        )
    ]


def row(
    feed: peri_scribe.sources.feed_types.Feed,
    *,
    name: str | None,
    identifiers: tuple[str | None, str],
    parent: int | None,
    time: int,
    present: bool,
) -> dict[str, object]:
    """Unnamed source rows preserve relationship evidence independently of fire records.

    Args:
        feed: The actual configured WFIGS schema.
        name: Whether this row independently names a fire.
        identifiers: Raw primary and secondary columns, before normalization.
        parent: The declared parent, or an explicit release.
        time: The incident modification clock.
        present: Whether a relationship declaration is supplied.

    Returns:
        A complete raw row with all fields required by source parsing.
    """
    prefix = (
        ""
        if feed is peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED
        else "attr_"
    )
    attributes: dict[str, object] = {
        feed.fire_name_column: name,
        feed.status_column: "active",
        prefix + "IsCpxChild": str(parent is not None) if present else None,
        prefix + "CpxID": None if parent is None else f"identifier-{parent}",
        prefix + "CpxName": None,
        prefix + "ModifiedOnDateTime_dt": (
            tests.formal.helpers.complex_ownership.moment(time).isoformat()
        ),
    }
    attributes.update(zip(feed.fire_identifier_columns, identifiers, strict=True))
    for column in (
        feed.point_of_origin_state_column,
        feed.point_of_origin_fips_column,
        feed.observation_time_column,
    ):
        if column is not None:
            attributes.setdefault(column, None)
    return attributes


def write_history(case: Case, directory: pathlib.Path, order: str) -> pathlib.Path:
    """Real snapshot decoding must retain the same evidence as the Lean request.

    Args:
        case: Alias-bearing correction and its independent expected evidence.
        directory: Isolated storage for the source and parsed cache.
        order: Original, reversed, or duplicated source rows.

    Returns:
        The directory passed directly to production source reading.
    """
    feed = (
        peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED
        if case.location
        else peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    )
    rows = [
        row(
            feed,
            name=f"Fire {identifier}",
            identifiers=(f"identifier-{identifier}", f"identifier-{identifier + 3}"),
            parent=1 if identifier == 0 else None,
            time=0,
            present=identifier == 0,
        )
        for identifier in range(tests.formal.helpers.complex_ownership.FIRE_COUNT)
    ]
    rows.append(
        row(
            feed,
            name=None,
            identifiers=case.raw_identifiers,
            parent=case.parent,
            time=2,
            present=True,
        ),
    )
    if order == "reversed":
        rows.reverse()
    elif order == "duplicated":
        rows *= 2
    timestamp = int(tests.formal.helpers.complex_ownership.moment(3).timestamp()) * 1000
    path = directory / feed.name / "000___" / f"000001,lastEdit={timestamp}.gpkg"
    path.parent.mkdir(parents=True)
    geopandas.GeoDataFrame(
        rows,
        geometry=[shapely.Point(-120, 40)] * len(rows),
        crs="EPSG:4326",
    ).to_file(path, layer=feed.name, driver="GPKG")
    return directory
