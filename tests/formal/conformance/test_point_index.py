import collections
from itertools import starmap

import numpy as np

import spatial_data.point_index
import tests.formal.helpers.oracle
import tests.formal.helpers.point_index


def test_longitude_index_select_matches_lean_signed_coordinate_bags() -> None:
    cases = tests.formal.helpers.point_index.cases()
    results = tests.formal.helpers.oracle.evaluate(
        list(starmap(tests.formal.helpers.point_index.command, cases)),
        executable="oracleSpatial",
    )
    for (points, box), result in zip(cases, results, strict=True):
        index = spatial_data.point_index.LongitudeIndex.build(
            np.array(points, dtype="<i4").reshape(-1, 2),
        )
        actual = collections.Counter(map(tuple, index.select(box).tolist()))
        expected = collections.Counter(zip(result[::2], result[1::2], strict=True))
        assert actual == expected, (points, box)
