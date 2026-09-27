import dataclasses
import itertools
import json

import peri_scribe.fire_updates
import tests.formal.helpers.identity
import tests.formal.helpers.oracle


def test_matching_name_identities_matches_lean_unique_ownership() -> None:
    cases = tests.formal.helpers.identity.cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oracleDomain",
    )
    for case, result in zip(cases, expected, strict=True):
        fires, previous, signatures, sources, keys = (
            tests.formal.helpers.identity.fixture(
                case,
            )
        )
        actual = peri_scribe.fire_updates.matching_name_identities(
            fires,
            previous,
            signatures,
            sources,
            {key for index, key in enumerate(keys) if case.reserved & (1 << index)},
        )
        assert actual == {
            ("id", str(index)): keys[owner]
            for index, owner in enumerate(result)
            if owner >= 0
        }, case


def test_stable_identity_matches_lean_first_known_alias_despite_renaming() -> None:
    cases = list(itertools.product(range(-1, 2), repeat=2))
    expected = tests.formal.helpers.oracle.evaluate(
        [f"stable {first} {second}" for first, second in cases],
        executable="oracleDomain",
    )
    fires, previous, _signatures, _sources, keys = (
        tests.formal.helpers.identity.fixture(
            tests.formal.helpers.identity.Case(),
        )
    )
    for (first, second), result in zip(cases, expected, strict=True):
        state = previous.model_copy(
            update={
                "aliases": {
                    json.dumps(["id", identifier]): keys[owner]
                    for identifier, owner in (("a", first), ("b", second))
                    if owner >= 0
                },
            },
        )
        for name in ("Timber", "Renamed Complex", "Another Fire"):
            fire = dataclasses.replace(
                fires["id", "0"],
                name=name,
                identifiers=frozenset({"a", "b"}),
            )
            assert peri_scribe.fire_updates.stable_identity(fire, state) == (
                None if result[0] < 0 else keys[result[0]]
            )


def test_resolved_ownership_preserves_two_phase_adoption_and_reserved_owners() -> None:
    cases = [
        dataclasses.replace(case, active=3, reserved=0)
        for case in tests.formal.helpers.identity.cases()[::13]
    ]
    first_phase = tests.formal.helpers.oracle.evaluate(
        [dataclasses.replace(case, active=1).command() for case in cases],
        executable="oracleDomain",
    )
    second_phase = tests.formal.helpers.oracle.evaluate(
        [
            dataclasses.replace(
                case,
                active=2,
                reserved=0 if first[0] < 0 else 1 << first[0],
            ).command()
            for case, first in zip(cases, first_phase, strict=True)
        ],
        executable="oracleDomain",
    )
    for case, first, second in zip(cases, first_phase, second_phase, strict=True):
        fires, previous, signatures, sources, keys = (
            tests.formal.helpers.identity.fixture(
                case,
            )
        )
        first_identity = "name", "Timber"
        fires[first_identity] = dataclasses.replace(
            fires.pop(("id", "0")),
            identifiers=frozenset(),
        )
        signatures[first_identity] = signatures.pop(("id", "0"))
        sources[first_identity] = sources.pop(("id", "0"))
        current_identities = first_identity, ("id", "1")
        expected = first[0], second[1]
        result = peri_scribe.fire_updates.resolved_ownership(
            fires,
            previous,
            signatures,
            sources,
        ).keys
        assert len(set(result.values())) == len(fires)
        assert (
            result
            == peri_scribe.fire_updates.resolved_ownership(
                dict(reversed(tuple(fires.items()))),
                previous,
                signatures,
                sources,
            ).keys
        )
        for index, owner in enumerate(expected):
            if owner >= 0:
                assert result[current_identities[index]] == keys[owner]
            else:
                assert result[current_identities[index]] not in keys


def test_resolved_ownership_keeps_known_owner_after_alias_enrichment_and_rename() -> (
    None
):
    cases = list(itertools.product(range(-1, 2), (False, True), repeat=2))
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"stable {first if first >= 0 else 2 if direct_first else -1} "
            f"{second if second >= 0 else 3 if direct_second else -1}"
            for first, direct_first, second, direct_second in cases
        ],
        executable="oracleDomain",
    )
    fires, previous, _signatures, _sources, histories = (
        tests.formal.helpers.identity.fixture(tests.formal.helpers.identity.Case())
    )
    direct_keys = json.dumps(["id", "a"]), json.dumps(["id", "b"])
    keys = (*histories, *direct_keys)
    for (first, direct_first, second, direct_second), selected in zip(
        cases,
        expected,
        strict=True,
    ):
        if selected == (-1,):
            continue
        state = previous.model_copy(
            update={
                "aliases": {
                    json.dumps(["id", identifier]): keys[owner]
                    for identifier, owner in (("a", first), ("b", second))
                    if owner >= 0
                },
                "perimeters": previous.perimeters
                | {
                    key: frozenset()
                    for key, include in zip(
                        direct_keys,
                        (direct_first, direct_second),
                        strict=True,
                    )
                    if include
                },
            },
        )
        for name in ("Timber", "Renamed Complex"):
            fire = dataclasses.replace(
                fires["id", "0"],
                name=name,
                identifiers=frozenset({"a", "b", "new-alias"}),
            )
            identity = "id", "a"
            assert peri_scribe.fire_updates.resolved_ownership(
                {identity: fire},
                state,
                {identity: frozenset({"corrected-footprint"})},
                {identity: frozenset()},
            ).keys == {identity: keys[selected[0]]}
