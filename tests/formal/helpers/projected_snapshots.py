"""Compare complete projected snapshots with Lean's retained-prefix reference."""

import dataclasses
import itertools
import json

import peri_scribe.updates
import tests.formal.helpers.oracle
import tests.formal.helpers.update_viewer


type Key = tuple[int, int]
Observation = tests.formal.helpers.update_viewer.Observation
WINDOW = tests.formal.helpers.update_viewer.WINDOW


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Raw observations and current ownership remain independent oracle inputs."""

    history: tuple[Observation, ...]
    ownership: tuple[tuple[Key, Key], ...]

    def command(self) -> str:
        """Include unmapped keys and immutable log identities without resolving them.

        Returns:
            One complete snapshot request for the compiled reference.
        """
        assignments = (
            f"{source[0]},{source[1]},{owner[0]},{owner[1]}"
            for source, owner in self.ownership
        )
        return " ".join((
            "projected-snapshot",
            "0",
            str(WINDOW),
            *assignments,
            "--",
            *(row.text() for row in self.history),
        ))


def identity(key: Key) -> peri_scribe.updates.HistoryIdentity:
    """Decode independent typed tokens using the existing observation fixture grammar.

    Args:
        key: Identity kind and payload tokens supplied to the model.

    Returns:
        The exact production identity representation.
    """
    kind, payload = key
    return (
        ("id", "name", "local", "component")[kind],
        tests.formal.helpers.update_viewer.NAMES[payload]
        if kind == 1
        else str(payload),
    )


def token(key: tuple[str, str]) -> Key:
    """Encode an actual typed identity without making an ownership decision.

    Args:
        key: The original or projected identity from a real snapshot record.

    Returns:
        Its independently assigned oracle tokens.
    """
    kind, payload = key
    return (
        ("id", "name", "local", "component").index(kind),
        tests.formal.helpers.update_viewer.NAMES.index(payload)
        if kind == "name"
        else int(payload),
    )


def observations(
    keys: tuple[Key, ...],
    times: tuple[int, ...],
    areas: tuple[int, ...],
    *,
    legacy: bool,
) -> tuple[Observation, ...]:
    """Attribute/display identity may change while the durable bucket remains fixed.

    Args:
        keys: Three distinct original typed identities.
        times: Observation instants relative to snapshot generation.
        areas: Exactly representable eighth-acre values.
        legacy: Omit saved log identities to exercise identifier/name fallback.

    Returns:
        Raw rows whose serials distinguish equal-time occurrences.
    """
    return tuple(
        Observation(
            serial=index,
            time=time,
            name=key[1] if key[0] == 1 else (index + 1) % 3,
            identifier=key[1] if key[0] == 0 else None,
            logged=None if legacy else key,
            area=area,
        )
        for index, (key, time, area) in enumerate(zip(keys, times, areas, strict=True))
    )


def cases() -> tuple[Case, ...]:
    """Exhaust partial maps and cross the temporal/acreage decisions they can change.

    Returns:
        Complete ownership/snapshot inputs, including reverse-order equal timestamps.
    """
    layouts = (
        ((0, 0), (0, 1), (0, 2)),
        ((1, 0), (1, 1), (1, 2)),
        ((2, 0), (2, 1), (2, 2)),
        ((0, 0), (1, 0), (2, 0)),
        ((3, 0), (3, 1), (3, 2)),
    )
    times = (
        (-WINDOW - 1, -WINDOW + 1, 0),
        (-WINDOW, -1, 0),
        (-1, 0, 1),
        (0, 0, 0),
        (1, -1, 0),
        (-WINDOW - 1, -WINDOW, 1),
    )
    areas = ((0, 0, 0), (0, 8, 8), (8, 8, 0), (24, 8, 24), (24, 0, 0), (0, 24, 8))
    result = []
    for keys, selected, sizes, owners in itertools.product(
        layouts,
        times,
        areas,
        itertools.product((None, 0, 1, 2), repeat=3),
    ):
        ownership = tuple(
            (key, keys[owner])
            for key, owner in zip(keys, owners, strict=True)
            if owner is not None
        )
        history = observations(keys, selected, sizes, legacy=False)
        result.extend(
            Case(history=ordered, ownership=ownership)
            for ordered in (history, tuple(reversed(history)))
        )
    for keys, sizes, owners in itertools.product(
        layouts[:2],
        areas,
        itertools.product((None, 0, 1, 2), repeat=3),
    ):
        ownership = tuple(
            (key, keys[owner])
            for key, owner in zip(keys, owners, strict=True)
            if owner is not None
        )
        history = observations(keys, times[0], sizes, legacy=True)
        result.extend(
            Case(history=ordered, ownership=ownership)
            for ordered in (history, tuple(reversed(history)))
        )
    return tuple(result)


def compare(catalogue: tuple[Case, ...]) -> int:
    """Require exact inclusion, ordering, immutable payload, owner, and previous area.

    Args:
        catalogue: Raw snapshots and partial one-hop ownership maps.

    Returns:
        Complete snapshot comparisons evaluated by the compiled formal reference.
    """
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in catalogue],
        executable="oraclePresentationFlow",
    )
    for case, answer in zip(catalogue, expected, strict=True):
        entries = tuple(row.record() for row in case.history)
        originals = {entry.batch_id: entry for entry in entries}
        ownership = {
            identity(source): identity(owner) for source, owner in case.ownership
        }
        snapshot = peri_scribe.updates.snapshot_from_entries(
            entries,
            tests.formal.helpers.update_viewer.NOW,
            owners={
                json.dumps(source): json.dumps(owner)
                for source, owner in ownership.items()
            },
        )
        observed = []
        for update in snapshot.updates:
            assert update.batch_id is not None
            original = originals[update.batch_id]
            assert (
                update.model_dump(
                    exclude={"history_identity", "previous_mapped_area"},
                )
                == original.model_dump()
            )
            assert update.history_identity == ownership.get(original.identity())
            observed.extend((
                int(update.batch_id),
                *token(update.identity()),
                *token(update.history_identity or update.identity()),
                -1
                if update.previous_mapped_area is None
                else int(update.previous_mapped_area.value * 8),
            ))
        assert tuple(observed) == answer, case
        assert (
            peri_scribe.updates.Snapshot.model_validate_json(
                snapshot.model_dump_json(),
            )
            == snapshot
        )
    return len(catalogue)
