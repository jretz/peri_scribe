"""Compare retained reverse dependencies with the proved finite path definition."""

from __future__ import annotations

import dataclasses
import itertools

import peri_scribe.fires.source_index_cache
import tests.formal.helpers.oracle


REFERENCES = (("feed/0.gpkg", 0), ("feed/0.gpkg", 1), ("feed/1.gpkg", 0))
HISTORY_COUNT = 15_625


@dataclasses.dataclass(frozen=True, kw_only=True)
class Inventory:
    """Keep concrete summaries beside their independent symbolic evidence table."""

    index: peri_scribe.fires.source_index_cache.DependencyIndex
    evidence: tuple[tuple[int, int], ...]
    edges: tuple[tuple[int, int], ...]


def inventories(*, mixed_tags: bool) -> list[Inventory]:
    """Enumerate absent rows, two keys, their bridge, and changed evidence for one key.

    Args:
        mixed_tags: Whether the second incidence uses a name with the identifier's text.

    Returns:
        All five symbolic states on each of three independently retained occurrences.
    """
    result = []
    for states in itertools.product(range(5), repeat=len(REFERENCES)):
        rows = []
        evidence = []
        for position, state in enumerate(states):
            if not state:
                continue
            first = state in {1, 3, 4}
            second = state in {2, 3}
            identifiers = {"shared"} if first else set()
            names: set[str] = set()
            if second:
                if mixed_tags:
                    names.add("shared")
                else:
                    identifiers.add("second")
            path, ordinal = REFERENCES[position]
            rows.append(
                peri_scribe.fires.source_index_cache.DependencyRow(
                    path=path,
                    position=ordinal,
                    evidence_key=f"complete-evidence-{state}",
                    identifiers=frozenset(identifiers),
                    names=frozenset(names),
                ),
            )
            evidence.append((position, state))
        index = peri_scribe.fires.source_index_cache.index_from_rows(tuple(rows))
        restored = (
            peri_scribe.fires.source_index_cache.DependencyIndex.model_validate_json(
                index.model_dump_json(),
            )
        )
        assert restored == index
        edges = tuple(
            (REFERENCES.index(left.reference), REFERENCES.index(right.reference))
            for left, right in itertools.combinations(rows, 2)
            if left.identifiers & right.identifiers or left.names & right.names
        )
        result.append(Inventory(index=restored, evidence=tuple(evidence), edges=edges))
    return result


def pair_tokens(pairs: tuple[tuple[int, int], ...]) -> list[str]:
    """Transport exact edge and evidence pairs without implementing path closure.

    Args:
        pairs: Ordered occurrence/evidence pairs or independently derived incidences.

    Returns:
        Comma-separated pairs understood by the executable Lean transport.
    """
    return [f"{left},{right}" for left, right in pairs]


def compare_histories(*, mixed_tags: bool) -> int:
    """Compare every bounded edit with compiled change detection and path closure.

    Args:
        mixed_tags: Whether identifier/name values deliberately share the same text.

    Returns:
        The number of complete previous/current inventory pairs checked.
    """
    cases = inventories(mixed_tags=mixed_tags)
    histories = list(itertools.product(cases, repeat=2))
    seeds = tests.formal.helpers.oracle.evaluate(
        [
            " ".join([
                "changed",
                *map(str, range(len(REFERENCES))),
                "--",
                *pair_tokens(before.evidence),
                "--",
                *pair_tokens(after.evidence),
            ])
            for before, after in histories
        ],
        executable="oraclePresentationFlow",
    )
    closures = tests.formal.helpers.oracle.evaluate(
        [
            " ".join([
                "affected",
                *map(str, (position for position, _ in after.evidence)),
                "--",
                *map(str, changed),
                "--",
                *pair_tokens(before.edges),
                "--",
                *pair_tokens(after.edges),
            ])
            for (before, after), changed in zip(histories, seeds, strict=True)
        ],
        executable="oraclePresentationFlow",
    )
    for (before, after), changed, affected in zip(
        histories,
        seeds,
        closures,
        strict=True,
    ):
        assert peri_scribe.fires.source_index_cache.changed_rows(
            before.index,
            after.index,
        ) == {REFERENCES[position] for position in changed}
        assert peri_scribe.fires.source_index_cache.affected_rows(
            before.index,
            after.index,
        ) == {REFERENCES[position] for position in affected}
    for case in cases:
        assert peri_scribe.fires.source_index_cache.affected_rows(None, case.index) == {
            row.reference for row in case.index.rows
        }
    return len(histories)
