"""Keep source text separate from document syntax at serialization boundaries.

Design notes:
[Output serialization](../../docs/algorithms/output-serialization.md).
"""

from __future__ import annotations

import collections


MARKDOWN_RESERVED = frozenset("\t\n\r#&*<>[\\]_`|~")
XML_RESERVED = frozenset("\"&'<>")
XML_RANGES = ((0x20, 0xD7FF), (0xE000, 0xFFFD), (0x10000, 0x10FFFF))


def normalized(value: str) -> str:
    """Keep source text representable in both Markdown HTML and XML 1.0.

    CRLF, CR, and NEXT LINE line endings become LF. Unsupported XML controls, surrogate
    code points, and the two excluded BMP noncharacters become the visible replacement
    character. Supported Unicode text keeps its order and multiplicity.

    Args:
        value: Source-provided text before document encoding.

    Returns:
        Text with portable line endings and valid XML scalar values.
    """
    return "".join(
        character
        if (
            character in "\t\n"
            or any(lower <= ord(character) <= upper for lower, upper in XML_RANGES)
        )
        else "\ufffd"
        for character in value
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\x85", "\n")
    )


def encoded(value: str, reserved: frozenset[str]) -> str:
    """Use character references without letting source text acquire markup syntax.

    Boundary whitespace also use references so Markdown's cell trimming cannot discard
    them. Interior spaces remain readable in the source document.

    Args:
        value: Source text to normalize and encode.
        reserved: Characters whose literal spelling has structural meaning.

    Returns:
        Encoded source text suitable for its declared document context.
    """
    text = normalized(value)
    return "".join(
        f"&#{ord(character)};"
        if character in reserved
        or (character.isspace() and index in {0, len(text) - 1})
        else character
        for index, character in enumerate(text)
    )


def markdown(value: str) -> str:
    """Preserve literal source text inside an inline Markdown context.

    Args:
        value: A heading, table cell, or link label supplied by a source.

    Returns:
        Text that cannot add Markdown formatting, rows, columns, links, or HTML.
    """
    return encoded(value, MARKDOWN_RESERVED)


def xml(value: str) -> str:
    """Preserve source text as XML character data, including literal CDATA markers.

    Args:
        value: Source text inside an XML element.

    Returns:
        Normalized character data with all XML delimiters escaped.
    """
    return encoded(value, XML_RESERVED)


class Markdown(collections.UserString):
    """Mark generated Markdown whose source-provided parts were already encoded."""


class CData(collections.UserString):
    """Mark generated balloon HTML for the XML description channel alone."""

    def __init__(self, markup: str) -> None:
        """Keep generated HTML intact without permitting it to close the XML envelope.

        Args:
            markup: Generated HTML whose interpolated source text is already escaped.
        """
        super().__init__(
            "<![CDATA[" + normalized(markup).replace("]]>", "]]]]><![CDATA[>") + "]]>",
        )
