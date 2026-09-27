"""Interrupt serialization after bytes have reached their filesystem destination."""

import pathlib
import typing


class ProcessLoss(BaseException):
    """Represent termination outside ordinary exception recovery."""


def interrupt_json(
    _document: object,
    stream: typing.TextIO,
    **_options: object,
) -> None:
    """Leave incomplete JSON at the serializer's actual destination.

    Args:
        _document: Ignored input to the interrupted serializer.
        stream: The actual output stream.
        _options: Serialization options that do not affect the interruption.

    Raises:
        ProcessLoss: Bytes were written before termination.
    """
    stream.write('{"fires": [')
    stream.flush()
    raise ProcessLoss


def interrupt_text(
    path: pathlib.Path,
    text: str,
    *,
    encoding: str,
) -> int:
    """Leave a prefix at the writer's actual destination.

    Args:
        path: The path the production writer selected.
        text: Complete output that cannot finish writing.
        encoding: The writer's text encoding.

    Raises:
        ProcessLoss: Bytes were written before termination.
    """
    with path.open("w", encoding=encoding) as stream:
        stream.write(text[: len(text) // 2])
        stream.flush()
    raise ProcessLoss
