import pathlib

import tests.formal.helpers.journal
import tests.formal.helpers.journal_builder


def test_recover_updates_replays_every_checked_journal_recovery(
    tmp_path: pathlib.Path,
) -> None:
    outcomes = tests.formal.helpers.journal.recoveries(tmp_path / "tlc")
    for index, outcome in enumerate(outcomes):
        tests.formal.helpers.journal.replay(outcome, tmp_path / str(index) / "2026")


def test_create_kmz_real_files_match_checked_crash_prefixes(
    tmp_path: pathlib.Path,
) -> None:
    allowed = tests.formal.helpers.journal_builder.projections(tmp_path / "tlc")
    for prior_fresh, fresh in ((False, False), (True, False), (True, True)):
        for destination in (
            "kmz",
            "publication",
            "journal",
            "append",
            "checkpoint",
            "unlink journal",
            "viewer",
            "archive",
            "unlink plain",
        ):
            if destination == "publication" and not fresh:
                continue
            for after in (False, True):
                scenario = tests.formal.helpers.journal_builder.Scenario(
                    directory=tmp_path
                    / f"{prior_fresh}-{fresh}-{destination}-{after}"
                    / "2026",
                    allowed=allowed[prior_fresh, fresh],
                )
                tests.formal.helpers.journal_builder.replay(
                    scenario,
                    destination,
                    after=after,
                    fresh=fresh,
                    prior_fresh=prior_fresh,
                )
