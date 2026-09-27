import pathlib

import structlog.testing

import tests.formal.helpers.buildings_construction
import tests.formal.helpers.tlc


def test_fetch_buildings_database_matches_checked_lifecycle(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.tlc.states(
        "BuildingsConstruction",
        "BuildingsConstruction",
        tmp_path / "tlc",
    )
    with structlog.testing.capture_logs():
        for index, case in enumerate(
            tests.formal.helpers.buildings_construction.cases(states),
        ):
            tests.formal.helpers.buildings_construction.replay(
                case,
                states,
                tmp_path / str(index),
            )
