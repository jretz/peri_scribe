"""Recognize trailing civil aircraft registrations without registry lookups.

Recognition uses ICAO-notified marks and Annex 7 syntax, refined by sourced national
formats. It establishes a possible registration, not whether a mark has been issued.
Source dates, exceptions, and coverage limits are documented in
``docs/aircraft_registration.md``.
"""

from __future__ import annotations

import dataclasses
import re

import aircraft_registration.formats


@dataclasses.dataclass(frozen=True, kw_only=True)
class TailNumberSplit:
    """Keep caller-owned text separate from a normalized aircraft registration."""

    prefix: str
    tail_number: str


TAIL_NUMBER_PATTERN = re.compile(
    "(?:" + "|".join(aircraft_registration.formats.registration_patterns()) + ")\\Z",
    re.IGNORECASE | re.ASCII,
)


def split_tail_number(text: str) -> TailNumberSplit | None:
    """Separate a complete trailing registration from the caller's original prefix.

    A registration starts at the beginning of the string or after whitespace or a
    hyphen. The longest complete suffix wins, preserving hyphens inside registrations.
    Separating whitespace and hyphens are removed from the end of the prefix; its
    other characters and case are preserved. Trailing whitespace is ignored. Only the
    registration is uppercased. Abbreviated callsigns are not registrations.

    Args:
        text: A registration alone or text ending with a registration.

    Returns:
        The prefix and uppercase registration, or None when no complete suffix matches.

    Examples:
        >>> split_tail_number("CA-YNP-DOME-N5852K")
        TailNumberSplit(prefix='CA-YNP-DOME', tail_number='N5852K')
        >>> split_tail_number("Dome-c-fabc")
        TailNumberSplit(prefix='Dome', tail_number='C-FABC')
        >>> split_tail_number("N874EB")
        TailNumberSplit(prefix='', tail_number='N874EB')
        >>> split_tail_number("DOME") is None
        True
    """
    candidate = text.rstrip()
    for start in re.finditer(r"(?<![^\s-])[A-Za-z0-9]", candidate):
        match = TAIL_NUMBER_PATTERN.fullmatch(candidate, start.start())
        if match is not None:
            prefix = candidate[: start.start()]
            while prefix and (prefix[-1].isspace() or prefix[-1] == "-"):
                prefix = prefix[:-1]
            return TailNumberSplit(prefix=prefix, tail_number=match[0].upper())
    return None
