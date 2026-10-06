"""All authoritative CLI writers share the checked recovery and exclusion boundary."""

import pathlib

import click

import peri_scribe.main
import tests.formal.helpers.corpus
import tests.formal.helpers.source_commands


def test_validate_sources_matches_checked_writer_recovery(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "SourceWriters",
        "SourceWriters",
        tmp_path,
    )
    tests.formal.helpers.source_commands.replay(states, tmp_path / "commands")


def test_commands_list_commands_keeps_source_writer_audit_complete() -> None:
    assert set(
        peri_scribe.main.cli.list_commands(click.Context(peri_scribe.main.cli)),
    ) == {
        "run",
        "validate-sources",
        "monitor",
        "show-colormap",
        "show-latencies",
        "version",
    }
