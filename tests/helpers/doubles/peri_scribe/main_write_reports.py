"""Replace main write reports dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.report.gathering


def make_report_gatherer(
    *,
    gathered: list[pathlib.Path],
    report: peri_scribe.report.gathering.FireReport,
) -> typing.Callable[..., peri_scribe.report.gathering.FireReport]:
    """Create a callback to capture the directory used to gather report data.

    Args:
        gathered: Shared list recording directories used to gather report data.
        report: Controlled report returned by the gathering callback.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def gather_report(
        directory: pathlib.Path,
    ) -> peri_scribe.report.gathering.FireReport:
        """Capture the directory used to gather report data.

        Args:
            directory: Directory supplied to the intercepted storage operation.

        Returns:
            The report supplied by the test.
        """
        gathered.append(directory)
        return report

    return gather_report


def make_report_renderer(
    *,
    rendered: list[tuple[peri_scribe.report.gathering.FireReport, pathlib.Path]],
    output: pathlib.Path,
) -> typing.Callable[..., pathlib.Path]:
    """Create a callback to capture the report and directory passed to the renderer.

    Args:
        rendered: Shared list recording report data and output directories.
        output: Output path used by the controlled write or renderer.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def render_markdown_report(
        gathered_report: peri_scribe.report.gathering.FireReport,
        directory: pathlib.Path,
    ) -> pathlib.Path:
        """Capture the report and directory passed to the renderer.

        Args:
            gathered_report: Report data passed from gathering to rendering.
            directory: Directory supplied to the intercepted storage operation.

        Returns:
            The configured report output path.
        """
        rendered.append((gathered_report, directory))
        return output

    return render_markdown_report
