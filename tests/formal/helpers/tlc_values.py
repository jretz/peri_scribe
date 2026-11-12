"""Decode scalar collections from TLC without loading a domain adapter."""

import re


def numbers(value: str) -> tuple[int, ...]:
    """Retain natural numbers in the order TLC printed them.

    Args:
        value: TLC's numeric set or sequence representation.

    Returns:
        The numbers in their printed order.
    """
    return tuple(map(int, re.findall(r"\d+", value)))
