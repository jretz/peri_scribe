"""Resolve saved scores once against the complete collection of showable identities.

[Algorithm note](../../../docs/algorithms/presentation-selection.md)
"""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import peri_scribe.models


def associated_scores(
    identities: typing.Sequence[tuple[str, frozenset[str]]],
    scores: peri_scribe.models.FireScores,
    *,
    component_ids: typing.Sequence[str | None] | None = None,
) -> dict[int, peri_scribe.models.FireScoreEntry]:
    """Keep one winning score and its explanation for each resolved output fire.

    Identifier matches take priority, followed by exact component identity. Legacy
    scores without a component fall back to the final same-name fire. Every owner keeps
    its highest-ranked score, with stable score-name ordering for ties.

    Args:
        identities: Showable fire names and identifier aliases, in output input order.
        scores: Saved score rows, including rows for excluded fires.
        component_ids: Internal source identities aligned with the output fires.

    Returns:
        Winning rows keyed by input position, in descending score order.
    """
    by_identifier = {
        identifier: index
        for index, (_name, identifiers) in enumerate(identities)
        for identifier in identifiers
    }
    by_name = {name: index for index, (name, _identifiers) in enumerate(identities)}
    by_component = {
        component: index
        for index, component in enumerate(component_ids or ())
        if component is not None
    }
    selected: dict[int, peri_scribe.models.FireScoreEntry] = {}
    for entry in sorted(
        scores.fires,
        key=lambda entry: (-entry.score, entry.name.casefold()),
    ):
        owner = (
            by_identifier.get(entry.identifier)
            if entry.identifier is not None
            else None
        )
        if owner is None:
            owner = (
                by_component.get(entry.component_id)
                if entry.component_id is not None
                else by_name.get(entry.name)
            )
        if owner is not None:
            selected.setdefault(owner, entry)
    return selected
