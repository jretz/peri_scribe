"""Preserve arbitrary prefix text and recognize the full US numeric range."""

import hypothesis
import hypothesis.strategies

import aircraft_registration


@hypothesis.given(
    prefix=hypothesis.strategies.text(),
    number=hypothesis.strategies.integers(min_value=1, max_value=99999),
)
def test_split_tail_number_preserves_prefix_before_whitespace(
    prefix: str,
    number: int,
) -> None:
    prefix = prefix.rstrip()
    while prefix.endswith("-"):
        prefix = prefix[:-1].rstrip()
    assert aircraft_registration.split_tail_number(f"{prefix} n{number}") == (
        aircraft_registration.TailNumberSplit(prefix=prefix, tail_number=f"N{number}")
    )


@hypothesis.given(
    number=hypothesis.strategies.integers(min_value=1, max_value=999),
    letters=hypothesis.strategies.text(
        alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ",
        min_size=2,
        max_size=2,
    ),
)
def test_split_tail_number_returned_registration_is_idempotent(
    number: int,
    letters: str,
) -> None:
    split = aircraft_registration.split_tail_number(f"Dome-n{number}{letters.lower()}")
    assert split is not None
    assert aircraft_registration.split_tail_number(split.tail_number) == (
        aircraft_registration.TailNumberSplit(
            prefix="",
            tail_number=f"N{number}{letters}",
        )
    )
