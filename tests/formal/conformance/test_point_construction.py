import pathlib

import tests.formal.helpers.point_construction


def test_build_tiles_database_preserves_proved_point_bags(
    tmp_path: pathlib.Path,
) -> None:
    for index, points in enumerate(tests.formal.helpers.point_construction.cases()):
        for chunk_size in (1, 3, 17):
            tests.formal.helpers.point_construction.replay(
                points,
                chunk_size,
                tmp_path / f"{index}-{chunk_size}",
            )
