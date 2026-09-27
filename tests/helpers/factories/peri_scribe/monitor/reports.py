"""Generated reports expose monitor compatibility with published Markdown."""

import pathlib

import peri_scribe.report.gathering
import peri_scribe.report.markdown
import tests.helpers.factories.peri_scribe.report.markdown


def generated_report(directory: pathlib.Path, names: tuple[str, ...]) -> str:
    """Keep monitor navigation tests tied to the report readers receive.

    Args:
        directory: Isolated storage for the generated report.
        names: Fire names in summary and detail order, including possible collisions.

    Returns:
        The published Markdown, with a distinct fire identity for each name.
    """
    entries = tuple(
        tests.helpers.factories.peri_scribe.report.markdown.make_entry(
            name,
            identifier=f"fire-{index}",
        )
        for index, name in enumerate(names)
    )
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        type_one_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=entries,
        fire_details=entries,
    )
    return peri_scribe.report.markdown.render_markdown_report(
        report,
        directory / "2026",
    ).read_text()
