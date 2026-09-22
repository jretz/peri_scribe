"""Generate descriptions examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies


def balloon_text() -> hypothesis.strategies.SearchStrategy[str]:
    """Exercise both markup escaping layers with XML-compatible display text.

    Returns:
        Unicode text including HTML punctuation, entity spellings, and CDATA endings.
    """
    return hypothesis.strategies.one_of(
        hypothesis.strategies.text(
            alphabet=hypothesis.strategies.characters(
                exclude_categories=("Cc", "Cs"),
                exclude_characters=("\ufffe", "\uffff"),
            ),
            max_size=40,
        ),
        hypothesis.strategies.sampled_from([
            "]]>",
            "&amp;",
            '<b title="quoted">text</b>',
            "O'Brien & Sons",
        ]),
    )
