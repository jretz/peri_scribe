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
        # The checked path fixes both modes from its initial state.
        group = tmp_path / f"{prior_fresh}-{fresh}"
        first = tests.formal.helpers.journal_builder.Scenario(
            directory=group / "first" / "2026",
            allowed=allowed[prior_fresh, fresh],
        )
        tests.formal.helpers.journal_builder.initial_publication(
            first,
            fresh=prior_fresh,
        )
        rotation = first.branch(group / "rotation" / "2026")
        tests.formal.helpers.journal_builder.interrupt_before_rotation(
            rotation,
            fresh=fresh,
        )
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
            prefix = (
                rotation
                if destination
                in tests.formal.helpers.journal_builder.ROTATION_DESTINATIONS
                else first
            )
            for after in (False, True):
                tests.formal.helpers.journal_builder.replay(
                    prefix.branch(group / f"{destination}-{after}" / "2026"),
                    destination,
                    after=after,
                    fresh=fresh,
                )
