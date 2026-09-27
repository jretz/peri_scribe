import pytest

import spatial_data.cache_values
import tests.formal.helpers.cache_codec


def test_cache_values_preserve_declared_types_and_exact_representations() -> None:
    tests.formal.helpers.cache_codec.compare_round_trips()


def test_cache_values_encoding_equality_matches_lean_typed_tree_equality() -> None:
    tests.formal.helpers.cache_codec.compare_distinctions()


def test_cache_values_prefix_contract_rejects_missing_and_trailing_children() -> None:
    tests.formal.helpers.cache_codec.compare_framing()


@pytest.mark.parametrize(
    "representation",
    [
        ["none", 1],
        ["bool", 1],
        ["int", "01"],
        ["float", "0000"],
        ["datetime", "2026-09-01", 2],
        ["enum", "os.system", ["str", "ignored"]],
        ["quantity", ["list", []], "meter"],
        ["dict", [[["str", "a"], ["int", "1"]], [["str", "a"], ["int", "2"]]]],
        ["frozenset", [["str", "a"], ["str", "a"]]],
        ["numpy", "O", "0000000000000000"],
    ],
)
def test_cache_values_loads_rejects_noncanonical_or_unapproved_shapes(
    representation: list[object],
) -> None:
    with pytest.raises(ValueError, match=r"[Cc]ache|NumPy|fold"):
        spatial_data.cache_values.loads(
            tests.formal.helpers.cache_codec.canonical_payload(representation),
        )
