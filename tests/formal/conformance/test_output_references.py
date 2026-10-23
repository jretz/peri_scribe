"""Complete serialized artifacts retain collision-safe, source-owned references."""

import pathlib
import unittest.mock

import pytest

import tests.formal.helpers.oracle
import tests.formal.helpers.output_artifacts
import tests.formal.helpers.output_monitor
import tests.formal.helpers.output_references


def test_unique_filename_prefix_matches_fresh_allocation() -> None:
    with unittest.mock.patch.object(
        tests.formal.helpers.oracle,
        "evaluate",
        wraps=tests.formal.helpers.oracle.evaluate,
    ) as evaluate:
        tests.formal.helpers.output_references.check_prefixes()
    evaluate.assert_called_once()
    expected_allocations = 180
    assert len(evaluate.call_args.args[0]) == expected_allocations


def test_check_prefixes_rejects_an_incorrect_final_allocation() -> None:
    evaluate = tests.formal.helpers.oracle.evaluate

    def incorrect_final_allocation(
        commands: list[str],
        *,
        executable: str,
    ) -> list[tuple[int, ...]]:
        """Choose another valid index in the final case's table of at least two names.

        Args:
            commands: Every independent allocation request in its original order.
            executable: The proved allocation oracle used by the real comparison.

        Returns:
            Current reference replies with only the final allocation changed.
        """
        responses = evaluate(commands, executable=executable)
        responses[-1] = ((responses[-1][0] + 1) % 2,)
        return responses

    with (
        unittest.mock.patch.object(
            tests.formal.helpers.oracle,
            "evaluate",
            side_effect=incorrect_final_allocation,
        ),
        pytest.raises(AssertionError),
    ):
        tests.formal.helpers.output_references.check_prefixes()


@pytest.mark.parametrize(
    "names",
    [
        ("Bug", "Bug!", "Bug-1", "Top"),
        ("Same", "Same", "same", "SAME"),
        ("Fire Details", "Type 1", "PeriScribe Fires 2026", "Other"),
        ("A--B", "--A--", "A  B", "A & B"),
        ("**Bold**", "Café", "under_score", "[name]"),
    ],
)
def test_markdown_report_links_retain_detail_ownership(
    tmp_path: pathlib.Path,
    names: tuple[str, ...],
) -> None:
    tests.formal.helpers.output_references.check_markdown(tmp_path / "2026", names)


@pytest.mark.parametrize(
    "names",
    [
        ("Same", "Same", "same", "Top"),
        ("Fire Details", "A--B", "A  B", "<a id='fire-detail:0'>North</a>"),
    ],
)
@pytest.mark.asyncio
async def test_report_viewer_links_retain_detail_ownership(
    tmp_path: pathlib.Path,
    names: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await tests.formal.helpers.output_monitor.check_report(
        tmp_path / "2026",
        names,
        monkeypatch,
    )


@pytest.mark.parametrize("counts", [(0, 1, 2, 3), (3, 2, 1, 0)])
def test_write_fire_kml_archive_references_match_owned_resources(
    tmp_path: pathlib.Path,
    counts: tuple[int, ...],
) -> None:
    tests.formal.helpers.output_artifacts.check_archive(tmp_path, counts)
