"""Generate geometry examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies


def xml_text() -> hypothesis.strategies.SearchStrategy[str]:
    """Allow XML punctuation without accidentally creating CDATA delimiters.

    Returns:
        XML-compatible text with varied Unicode characters and no square brackets.
    """
    return hypothesis.strategies.text(
        alphabet=hypothesis.strategies.characters(
            exclude_categories=("Cc", "Cs"),
            exclude_characters=("[", "]", "\ufffe", "\uffff"),
        ),
        max_size=100,
    )
