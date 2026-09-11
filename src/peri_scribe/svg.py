"""Measuring text and sharing conventions for the SVG PeriScribe generates.

Google Earth renders balloon content in a WebKit view, and both the fire plots embedded
in the KMZ and the fire-scores chart are generated as SVG. SVG gives the generator no
way to measure text, so every piece of layout that depends on how wide a label is --
axis margins, the room kept for the outermost tick labels, legend centring -- is
computed from the advance-width table below.

The widths describe Helvetica. A viewer that substitutes a font with different metrics
shifts the spacing; labels are anchored with ``text-anchor`` so placement never breaks,
only the spacing around it.
"""

from __future__ import annotations

import html


# The font stack every generated SVG declares. Google Earth substitutes a system font
# when one is missing, so the families run most- to least-preferred and end generic.
FONT_STACK = "Helvetica, Arial, sans-serif"

# Helvetica advance widths in 1/1000 em, from the font's AFM metrics. The table covers
# printable ASCII; anything else falls back to DEFAULT_ADVANCE. Every entry matches the
# advances the system Helvetica reports for the same character, so a viewer that renders
# the declared font lays the chart out at the width this module measured.
HELVETICA_ADVANCES: dict[str, int] = {
    " ": 278,
    "!": 278,
    '"': 355,
    "#": 556,
    "$": 556,
    "%": 889,
    "&": 667,
    "'": 191,
    "(": 333,
    ")": 333,
    "*": 389,
    "+": 584,
    ",": 278,
    "-": 333,
    ".": 278,
    "/": 278,
    "0": 556,
    "1": 556,
    "2": 556,
    "3": 556,
    "4": 556,
    "5": 556,
    "6": 556,
    "7": 556,
    "8": 556,
    "9": 556,
    ":": 278,
    ";": 278,
    "<": 584,
    "=": 584,
    ">": 584,
    "?": 556,
    "@": 1015,
    "A": 667,
    "B": 667,
    "C": 722,
    "D": 722,
    "E": 667,
    "F": 611,
    "G": 778,
    "H": 722,
    "I": 278,
    "J": 500,
    "K": 667,
    "L": 556,
    "M": 833,
    "N": 722,
    "O": 778,
    "P": 667,
    "Q": 778,
    "R": 722,
    "S": 667,
    "T": 611,
    "U": 722,
    "V": 667,
    "W": 944,
    "X": 667,
    "Y": 667,
    "Z": 611,
    "[": 278,
    "\\": 278,
    "]": 278,
    "^": 469,
    "_": 556,
    "`": 333,
    "a": 556,
    "b": 556,
    "c": 500,
    "d": 556,
    "e": 556,
    "f": 278,
    "g": 556,
    "h": 556,
    "i": 222,
    "j": 222,
    "k": 500,
    "l": 222,
    "m": 833,
    "n": 556,
    "o": 556,
    "p": 556,
    "q": 556,
    "r": 333,
    "s": 500,
    "t": 278,
    "u": 556,
    "v": 500,
    "w": 722,
    "x": 500,
    "y": 500,
    "z": 500,
    "{": 334,
    "|": 260,
    "}": 334,
    "~": 584,
}

# The advance assumed for a character the table does not cover.
DEFAULT_ADVANCE = 556


def escape_text(value: str) -> str:
    """Return *value* escaped for use as SVG text or an XML attribute.

    Args:
        value: The text to escape.

    Returns:
        The escaped text.

    Examples:
        >>> escape_text("Miles & acres")
        'Miles &amp; acres'
        >>> escape_text('say "hi"')
        'say &quot;hi&quot;'
    """
    return html.escape(value, quote=True)


def text_width(text: str, font_size: float) -> float:
    """Return the width *text* occupies when drawn at *font_size* pixels.

    Args:
        text: The text to measure.
        font_size: The font size the text is drawn at, in pixels.

    Returns:
        The width in pixels.

    Examples:
        >>> round(text_width("Miles", 14), 3)
        32.662
        >>> text_width("", 14)
        0.0
    """
    advances = sum(
        HELVETICA_ADVANCES.get(character, DEFAULT_ADVANCE) for character in text
    )
    return advances / 1000.0 * font_size
