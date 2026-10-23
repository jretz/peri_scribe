"""Report Top Fires shares Holding exclusion with every ranked map view."""

import dataclasses
import pathlib

import peri_scribe.models
import peri_scribe.report.gathering
import tests.helpers.factories.peri_scribe.presentation.views


def test_report_from_fires_excludes_holding_from_top_fires(
    tmp_path: pathlib.Path,
) -> None:
    holding, active, inactive = (
        dataclasses.replace(
            tests.helpers.factories.peri_scribe.presentation.views.active_fire(
                name,
                identifiers=frozenset({identifier}),
            ),
            status=status,
        )
        for name, identifier, status in (
            ("Timber", "holding", peri_scribe.models.FireStatus.HOLDING),
            ("Timber", "active", peri_scribe.models.FireStatus.ACTIVE),
            ("Inactive", "inactive", peri_scribe.models.FireStatus.INACTIVE),
        )
    )
    scores = peri_scribe.models.FireScores(
        version="regression",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                name,
                identifier,
                score,
                "",
            )
            for name, identifier, score in (
                ("Timber", "holding", 100),
                ("Inactive", "inactive", 50),
                ("Timber", "active", 1),
            )
        ],
    )

    report = peri_scribe.report.gathering.report_from_fires(
        [holding, active, inactive],
        scores,
        tmp_path,
    )

    assert [(entry.identifier, entry.score) for entry in report.top_fires] == [
        ("inactive", 50),
        ("active", 1),
    ]
