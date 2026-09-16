"""Generate database examples with constrained domains."""

from __future__ import annotations

import datetime

import hypothesis.strategies

import peri_scribe.geo.package
import peri_scribe.models
import tests.helpers.strategies.geometry


def snapshot_contents() -> hypothesis.strategies.SearchStrategy[
    peri_scribe.geo.package.GeopackageContents
]:
    """Exercise cache serialization across optional fields, sets, and nested attributes.

    Returns:
        Small parsed snapshots, including empty row and membership collections.
    """
    text = hypothesis.strategies.text(max_size=12)
    optional_text = hypothesis.strategies.one_of(hypothesis.strategies.none(), text)
    value = hypothesis.strategies.recursive(
        hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.booleans(),
            hypothesis.strategies.integers(),
            hypothesis.strategies.floats(allow_nan=False, allow_infinity=False),
            text,
        ),
        lambda children: hypothesis.strategies.one_of(
            hypothesis.strategies.lists(children, max_size=3),
            hypothesis.strategies.dictionaries(text, children, max_size=3),
        ),
        max_leaves=10,
    )
    record = hypothesis.strategies.builds(
        peri_scribe.models.FireRecord,
        name=text,
        status=hypothesis.strategies.from_type(peri_scribe.models.FireStatus),
        identifiers=hypothesis.strategies.frozensets(text, max_size=3),
        names=hypothesis.strategies.frozensets(text, max_size=3),
        geometry=hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            tests.helpers.strategies.geometry.local_shapes(),
        ),
        observed_at=hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.datetimes(
                min_value=datetime.datetime(2000, 1, 1),
                max_value=datetime.datetime(2100, 1, 1),
                timezones=hypothesis.strategies.just(datetime.UTC),
            ),
        ),
        mission=optional_text,
        point_of_origin_state=optional_text,
        point_of_origin_fips=optional_text,
    )
    row = hypothesis.strategies.builds(
        peri_scribe.geo.package.FireRowRecord,
        record=record,
        object_id=hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.integers(0, 2**63 - 1),
        ),
        source_name=text,
        attributes=hypothesis.strategies.dictionaries(text, value, max_size=3),
    )
    membership = hypothesis.strategies.builds(
        peri_scribe.models.ComplexMembership,
        fire_identifier=text,
        complex_identifier=text,
        complex_name=text,
    )
    return hypothesis.strategies.builds(
        peri_scribe.geo.package.GeopackageContents,
        rows=hypothesis.strategies.lists(row, max_size=3).map(tuple),
        memberships=hypothesis.strategies.lists(membership, max_size=3).map(tuple),
    )
