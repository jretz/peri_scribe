"""Retained fire grouping keeps early unidentified records in one latency sample."""

from __future__ import annotations

import datetime
import json
import pathlib

import peri_scribe.show_latencies.perimeters
import peri_scribe.sources.feeds
import tests.helpers.factories.peri_scribe.show_latencies.evidence
import tests.helpers.factories.peri_scribe.show_latencies.sources
from measurement_units import units


def test_latencies_groups_unidentified_history_with_its_later_indexed_fire(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    paths = [
        tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
            tmp_path,
            feed,
            serial,
            published,
            [
                tests.helpers.factories.peri_scribe.show_latencies.sources.record(
                    feed,
                    serial,
                    identifier=identifier,
                    name="First Fire",
                ),
            ],
        )
        for serial, published, identifier in ((1, 10, None), (2, 30, "fire"))
    ]
    relative = [str(path.relative_to(tmp_path / "sources")) for path in paths]
    (tmp_path / "sources/fires.json").write_text(
        json.dumps({
            "fires": [
                {
                    "identifier": "fire",
                    "aliases": ["fire"],
                    "name": "First Fire",
                    "paths": relative,
                },
            ],
        }),
    )
    now = tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=(tests.helpers.factories.peri_scribe.show_latencies.evidence.run(),),
        snapshots={
            relative[0]: now + datetime.timedelta(seconds=20),
            relative[1]: now + datetime.timedelta(seconds=40),
        },
    )
    assert peri_scribe.show_latencies.perimeters.latencies(
        tmp_path,
        evidence,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    ) == (290 * units.seconds,)


def test_latencies_keeps_distinct_unidentified_indexed_fires_with_the_same_name(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    paths = [
        tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
            tmp_path,
            feed,
            serial,
            published,
            [
                tests.helpers.factories.peri_scribe.show_latencies.sources.record(
                    feed,
                    serial,
                    identifier=None,
                    name="Bear",
                ),
            ],
        )
        for serial, published in ((1, 10), (2, 30))
    ]
    relative = [str(path.relative_to(tmp_path / "sources")) for path in paths]
    (tmp_path / "sources/fires.json").write_text(
        json.dumps({
            "fires": [
                {"identifier": None, "name": "Bear", "paths": [path]}
                for path in relative
            ],
        }),
    )
    now = tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
    evidence = tests.helpers.factories.peri_scribe.show_latencies.evidence.evidence(
        runs=(tests.helpers.factories.peri_scribe.show_latencies.evidence.run(),),
        snapshots={
            relative[0]: now + datetime.timedelta(seconds=20),
            relative[1]: now + datetime.timedelta(seconds=40),
        },
    )
    assert sorted(
        peri_scribe.show_latencies.perimeters.latencies(
            tmp_path,
            evidence,
            tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
        ),
    ) == [270 * units.seconds, 290 * units.seconds]
