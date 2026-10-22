"""Enumerate finite bags and signed integer envelope boundaries for the Lean oracle."""

import itertools


def cases() -> list[tuple[tuple[tuple[int, int], ...], tuple[int, int, int, int]]]:
    """Exercise duplicates, order, exact endpoints, and reversed limits independently.

    Returns:
        Every bag of zero through two points on a three-by-three grid, paired with
        every envelope whose four limits belong to the grid's signed axes.
    """
    coordinates = [
        (longitude, latitude)
        for longitude, latitude in itertools.product((-1, 0, 1), repeat=2)
    ]
    bags = [
        bag
        for length in range(3)
        for bag in itertools.product(coordinates, repeat=length)
    ]
    boxes = [
        (minimum[0], minimum[1], maximum[0], maximum[1])
        for minimum, maximum in itertools.product(coordinates, repeat=2)
    ]
    return list(itertools.product(bags, boxes))


def command(points: tuple[tuple[int, int], ...], box: tuple[int, int, int, int]) -> str:
    """Pass signed native coordinates to the checked executable selection function.

    Args:
        points: Original tile occurrences, including duplicates.
        box: Inclusive coordinate limits, which may be reversed.

    Returns:
        One request for the existing spatial oracle.
    """
    return " ".join([
        "point-window",
        ",".join(map(str, box)),
        *(f"{longitude},{latitude}" for longitude, latitude in points),
    ])
