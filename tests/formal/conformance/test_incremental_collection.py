import contextlib
import datetime
import itertools
import pathlib
import sqlite3

import geopandas
import structlog.testing

import peri_scribe.sources.changes
import peri_scribe.sources.feed_state
import tests.formal.helpers.incremental_collection
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.sources.feed_types
import tests.helpers.factories.peri_scribe.sources.fetching


def test_fetch_feed_dataframe_matches_proved_eligibility() -> None:
    cases = tests.formal.helpers.incremental_collection.cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.incremental_collection.command(case) for case in cases],
        executable="oracleIngestion",
    )
    with structlog.testing.capture_logs():
        for case, result in zip(cases, expected, strict=True):
            tests.formal.helpers.incremental_collection.replay(case, result)


def test_where_clause_for_matches_lean_null_and_overlap_policy() -> None:
    cases = list(itertools.product((None, -6, -5, -4), repeat=3))
    expected = tests.formal.helpers.oracle.evaluate(
        [
            "recent -5 "
            + " ".join("null" if time is None else str(time) for time in case)
            for case in cases
        ],
        executable="oracleIngestion",
    )
    cutoff = tests.formal.helpers.incremental_collection.moment(-5)
    assert cutoff is not None
    columns = ("modified", "polygon_date", "other_date")
    predicate = peri_scribe.sources.feed_state.where_clause_for(columns, cutoff)
    with contextlib.closing(sqlite3.connect(":memory:")) as database:
        database.execute(
            "CREATE TABLE features (modified TEXT, polygon_date TEXT, other_date TEXT)",
        )
        for times, result in zip(cases, expected, strict=True):
            database.execute("DELETE FROM features")
            database.execute(
                "INSERT INTO features VALUES (?, ?, ?)",
                tuple(
                    tests.formal.helpers.incremental_collection.sql_time(time)
                    for time in times
                ),
            )
            rows = database.execute(
                "SELECT * FROM features WHERE " + predicate.replace("timestamp ", ""),
            ).fetchall()
            assert bool(rows) == bool(result[0]), times


def test_incremental_cutoff_matches_lean_across_columns_and_rows() -> None:
    cases = list(itertools.product((None, -10, 0, 7), repeat=4))
    epoch = datetime.datetime.fromtimestamp(0, tz=datetime.UTC)
    reference = (
        tests.helpers.factories.peri_scribe.sources.fetching.FETCH_REFERENCE_TIME
    )
    epoch_minute = int((epoch - reference).total_seconds() // 60)
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"cutoff 5 {epoch_minute} "
            + " ".join("null" if time is None else str(time) for time in times)
            for times in cases
        ],
        executable="oracleIngestion",
    )
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed(
        ("modified", "polygon_date"),
    )
    for times, result in zip(cases, expected, strict=True):
        frame = geopandas.GeoDataFrame({
            "modified": [
                tests.formal.helpers.incremental_collection.moment(t) for t in times[:2]
            ],
            "polygon_date": [
                tests.formal.helpers.incremental_collection.moment(t) for t in times[2:]
            ],
        })
        assert peri_scribe.sources.changes.incremental_cutoff(frame, feed) == (
            reference + datetime.timedelta(minutes=result[0])
        )


def test_fetch_feed_snapshot_matches_lean_metadata_skip(tmp_path: pathlib.Path) -> None:
    cases = list(itertools.product((False, True), repeat=2))
    expected = tests.formal.helpers.oracle.evaluate(
        [f"query {int(full)} {int(same)}" for full, same in cases],
        executable="oracleIngestion",
    )
    with structlog.testing.capture_logs():
        for index, ((full, same), result) in enumerate(
            zip(cases, expected, strict=True),
        ):
            assert tests.formal.helpers.incremental_collection.metadata_query(
                full=full,
                same=same,
                directory=tmp_path / str(index),
            ) == bool(result[0])
