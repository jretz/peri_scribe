"""Inline scalar equality agrees with complete typed evidence after arbitrary edits."""

import copy

import hypothesis
import hypothesis.strategies as st

import peri_scribe.geo.fingerprints
import tests.helpers.doubles.peri_scribe.geo.fingerprints
import tests.helpers.factories.peri_scribe.geo.fingerprints
import tests.helpers.reference.peri_scribe.geo.fingerprints
import tests.helpers.strategies.peri_scribe.geo.fingerprints


@hypothesis.given(
    left=tests.helpers.strategies.peri_scribe.geo.fingerprints.JSON_VALUES,
    right=tests.helpers.strategies.peri_scribe.geo.fingerprints.JSON_VALUES,
)
def test_same_json_value_matches_independent_typed_tree_evidence(
    left: object,
    right: object,
) -> None:
    assert peri_scribe.geo.fingerprints.same_json_value(left, right) is (
        tests.helpers.reference.peri_scribe.geo.fingerprints.same_json_value(
            left,
            right,
        )
    )
    detached = copy.deepcopy(left)
    assert peri_scribe.geo.fingerprints.same_json_value(left, detached) is (
        tests.helpers.reference.peri_scribe.geo.fingerprints.same_json_value(
            left,
            detached,
        )
    )


@hypothesis.given(
    original=tests.helpers.strategies.peri_scribe.geo.fingerprints.JSON_VALUES,
    replacement=tests.helpers.strategies.peri_scribe.geo.fingerprints.JSON_VALUES,
    position=st.integers(min_value=0),
)
def test_same_json_value_rechecks_every_mutated_container_and_leaf(
    original: object,
    replacement: object,
    position: int,
) -> None:
    template = copy.deepcopy(original)
    changed = tests.helpers.factories.peri_scribe.geo.fingerprints.changed_copy(
        original,
        replacement,
        position,
    )
    assert peri_scribe.geo.fingerprints.same_json_value(changed, template) is (
        tests.helpers.reference.peri_scribe.geo.fingerprints.same_json_value(
            changed,
            template,
        )
    )


@hypothesis.given(first=st.floats(), second=st.floats())
def test_same_json_value_preserves_generated_float_subclass_evidence(
    first: float,
    second: float,
) -> None:
    left = tests.helpers.doubles.peri_scribe.geo.fingerprints.TracedFloat(first)
    right = tests.helpers.doubles.peri_scribe.geo.fingerprints.TracedFloat(second)
    for current, retained in (
        (left, left),
        (left, right),
        (left, first),
        ([left], [right]),
        ({"value": left}, {"value": right}),
    ):
        assert peri_scribe.geo.fingerprints.same_json_value(current, retained) is (
            tests.helpers.reference.peri_scribe.geo.fingerprints.same_json_value(
                current,
                retained,
            )
        )
