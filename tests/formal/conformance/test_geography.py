import itertools

import peri_scribe.fires.differential
import tests.formal.helpers.geography
import tests.formal.helpers.oracle


def test_corrected_geometries_matches_lean_for_all_short_four_cell_histories() -> None:
    cases = [
        history
        for length in range(4)
        for history in itertools.product(
            range(1 << tests.formal.helpers.geography.CELL_COUNT),
            repeat=length,
        )
    ]
    expected = tests.formal.helpers.oracle.evaluate([
        " ".join(("corrected", *map(str, history))) for history in cases
    ])
    for history, result in zip(cases, expected, strict=True):
        geometries = [
            None
            if mask == 0 and index % 2
            else tests.formal.helpers.geography.footprint(mask)
            for index, mask in enumerate(history)
        ]
        corrected = peri_scribe.fires.differential.corrected_geometries(geometries)
        tests.formal.helpers.geography.assert_corrected(corrected, result)
