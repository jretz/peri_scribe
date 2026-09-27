"""Identity fixtures preserve ambiguity and continuity independently of hashes."""

import dataclasses
import itertools
import json

import numpy as np

import peri_scribe.fire_updates
import peri_scribe.models
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.selection


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Two histories and two claimants expose ambiguity in both matching directions."""

    active: int = 3
    reserved: int = 0
    local_aliases: int = 0
    preferred_first: int = -1
    preferred_second: int = -1
    history_signatures_first: int = 0
    history_signatures_second: int = 0
    history_sources_first: int = 0
    history_sources_second: int = 0
    fire_signatures_first: int = 0
    fire_signatures_second: int = 0
    fire_sources_first: int = 0
    fire_sources_second: int = 0

    def command(self) -> str:
        """Preserve masks for the Lean candidate and unique-claimant definitions.

        Returns:
            A request containing evidence, aliases, active fires, and reservations.
        """
        return "identity " + " ".join(
            str(getattr(self, field.name)) for field in dataclasses.fields(self)
        )


def members(mask: int) -> frozenset[str]:
    """Decode two independent pieces of mapping or source evidence.

    Args:
        mask: Finite evidence membership bits.

    Returns:
        String source tokens consumed by production identity selection.
    """
    return frozenset(str(index) for index in range(2) if mask & (1 << index))


def cases() -> list[Case]:
    """Exhaust ambiguity and vary source correction and local-alias preference.

    Returns:
        Explicit evidence combinations and reproducible mixed continuity cases.
    """
    result = [
        Case(
            reserved=reserved,
            history_signatures_first=first,
            history_signatures_second=second,
            fire_signatures_first=current_first,
            fire_signatures_second=current_second,
        )
        for reserved, first, second, current_first, current_second in itertools.product(
            range(4),
            repeat=5,
        )
    ]
    generator = np.random.default_rng(5978)
    for _ in range(1500):
        values = {
            field.name: int(generator.integers(4)) for field in dataclasses.fields(Case)
        }
        values["preferred_first"] = int(generator.integers(-1, 2))
        values["preferred_second"] = int(generator.integers(-1, 2))
        result.append(Case(**values))
    return result


def fixture(
    case: Case,
) -> tuple[
    dict[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.presentation.fire_data.FireSummary,
    ],
    peri_scribe.fire_updates.State,
    dict[peri_scribe.presentation.selection.AreaKey, frozenset[str]],
    dict[peri_scribe.presentation.selection.AreaKey, frozenset[str]],
    tuple[str, str],
]:
    """Keep raw alias spellings distinct while sharing one normalized historical name.

    Args:
        case: Evidence and ownership to construct.

    Returns:
        Production fires, historical state, signatures, sources, and historical keys.
    """
    keys = tuple(
        json.dumps([
            "local" if case.local_aliases & (1 << index) else "name",
            str(index),
        ])
        for index in range(2)
    )
    first_key, second_key = keys
    aliases = {
        json.dumps(["name", " timber " if index == 0 else " tImBeR  "]): key
        for index, key in enumerate(keys)
        if case.local_aliases & (1 << index)
    }
    for name, preferred in (
        ("Timber", case.preferred_first),
        ("TIMBER", case.preferred_second),
    ):
        if preferred >= 0:
            aliases[json.dumps(["name", name])] = keys[preferred]
    previous = peri_scribe.fire_updates.State(
        perimeters={
            first_key: members(case.history_signatures_first),
            second_key: members(case.history_signatures_second),
        },
        sources={
            first_key: members(case.history_sources_first),
            second_key: members(case.history_sources_second),
        },
        names={key: frozenset({"timber"}) for key in keys},
        aliases=aliases,
    )
    fires = {
        ("id", str(index)): peri_scribe.presentation.fire_data.FireSummary(
            name="Timber" if index == 0 else "TIMBER",
            identifiers=frozenset({str(index)}),
            status=peri_scribe.models.FireStatus.ACTIVE,
            point=None,
            perimeters=(),
        )
        for index in range(2)
        if case.active & (1 << index)
    }
    signatures = {
        ("id", "0"): members(case.fire_signatures_first),
        ("id", "1"): members(case.fire_signatures_second),
    }
    sources = {
        ("id", "0"): members(case.fire_sources_first),
        ("id", "1"): members(case.fire_sources_second),
    }
    return fires, previous, signatures, sources, (first_key, second_key)
