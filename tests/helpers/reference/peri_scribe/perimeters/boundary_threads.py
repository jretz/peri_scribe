"""Compare simultaneous native prepared predicates with an unprepared reference."""

from __future__ import annotations

import concurrent.futures
import json
import threading

import shapely

import peri_scribe.perimeters.classification_data


WORKERS = 8
REPETITIONS = 100


def compare_prepared_threads() -> dict[str, int | bool]:
    """Exercise lazy native indexes in separate prepared objects at the same time.

    Returns:
        Worker, predicate, and native-object counts after exact result comparison.
    """
    box = shapely.Point(0, 0).buffer(10, quad_segs=128)
    boundaries = peri_scribe.perimeters.classification_data.Boundaries(
        box=box,
        border=box.boundary,
    )
    geometries = [shapely.box(index - 12, -4, index - 10, 4) for index in range(24)]
    geometries.extend([
        shapely.LineString([(-11, -5), (9, 5), (-11, 6), (12, -5)]),
        shapely.Point(0, 0),
        shapely.Point(12, 0),
    ])
    expected = [(box.contains(shape), box.intersects(shape)) for shape in geometries]
    admitted = threading.Barrier(WORKERS)

    def compare(_worker: int) -> int:
        """Keep each worker's first native prepared query concurrent with the others.

        Args:
            _worker: Independent admitted worker position.

        Returns:
            The worker's retained native prepared geometry identity.

        Raises:
            AssertionError: A native result disagrees with the unprepared reference.
        """
        prepared = boundaries.prepared_box
        admitted.wait(timeout=10)
        for _ in range(REPETITIONS):
            actual = [
                (prepared.contains(shape), prepared.intersects(shape))
                for shape in geometries
            ]
            if actual != expected:
                message = "prepared predicates disagree with the unprepared reference"
                raise AssertionError(message)
        return id(prepared)

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
        identities = list(executor.map(compare, range(WORKERS)))
    return {
        "workers": WORKERS,
        "distinct_prepared_objects": len(set(identities)),
        "predicate_checks": WORKERS * REPETITIONS * len(geometries) * 2,
        "source_prepared": bool(shapely.is_prepared(box)),
    }


if __name__ == "__main__":
    print(json.dumps(compare_prepared_threads()))
