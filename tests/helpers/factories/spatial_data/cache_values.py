"""Build binary corruption cases independently of the production cache encoder."""


def node(tag: int, payload: bytes) -> bytes:
    """Frame explicit bytes using the documented one-byte tag and four-byte length.

    Args:
        tag: The declared value kind.
        payload: Its complete contents, possibly deliberately malformed.

    Returns:
        A node suitable for nesting inside another fixture.
    """
    return bytes((tag,)) + len(payload).to_bytes(4, "big") + payload


def invalid_values() -> tuple[bytes, ...]:
    """Exercise shape, framing, canonical ordering, and unsafe scalar rejection.

    Returns:
        Complete versioned roots with independently specified invalid contents.
    """
    key = node(6, b"key")
    number = node(4, b"1")
    invalid = (
        node(0, b"extra"),
        node(3, b""),
        node(3, b"\x02"),
        node(4, b"01"),
        node(5, b"short"),
        node(255, b""),
        node(8, b"\0"),
        b"\x08\xff\xff\xff\xff",
        node(11, key),
        node(11, key + number + key + number),
        node(10, key + key),
        node(18, node(6, b"O") + node(7, b"\0" * 8)),
        node(18, node(6, b"i4,i4") + node(7, b"\0" * 8)),
        node(18, node(6, b"i4") + node(7, b"")),
        node(18, node(6, b"i4") + node(7, b"\0" * 8)),
        node(15, node(6, b"NaT") + node(4, b"0") + node(6, b"ns")),
        node(17, number),
        node(13, node(9, b"") + node(6, b"acre")),
        node(13, number + node(6, b"not_an_existing_unit")),
        node(19, b"\0"),
    )
    return tuple(b"PSCV\x02" + content for content in invalid)
