"""Exercise reference allocation with actual names and serialized Markdown documents."""

from __future__ import annotations

import itertools
import pathlib

import lxml.html
import markdown_it

import peri_scribe.kml.fire_data
import peri_scribe.kml.plot_rendering
import peri_scribe.report.gathering
import peri_scribe.report.markdown
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.report.markdown


def allocated(used: set[str], candidates: list[str]) -> str:
    """Preserve string equality while Lean chooses the first unoccupied candidate.

    Args:
        used: Already assigned document or archive names.
        candidates: Distinct proposed names in their policy order.

    Returns:
        The fresh name selected by the proved allocation definition.
    """
    names = sorted(used | set(candidates))
    positions = {name: index for index, name in enumerate(names)}
    result = tests.formal.helpers.oracle.evaluate(
        [
            "allocate | "
            + " ".join(str(positions[name]) for name in sorted(used))
            + " | "
            + " ".join(str(positions[name]) for name in candidates),
        ],
        executable="oracleOutputs",
    )[0]
    assert len(set(candidates)) > len(used)
    assert len(result) == 1
    assert result[0] < len(names)
    return names[result[0]]


def check_prefixes() -> None:
    """Check filename allocation after case, punctuation and empty-name collapse."""
    for names in itertools.permutations(("Bug", "BUG!", "bug-2", "", "!!!"), 3):
        used: set[str] = set()
        for name in names:
            base = peri_scribe.kml.plot_rendering.filename_prefix(None, name)
            candidates = [base] + [
                f"{base}-{suffix}" for suffix in range(2, len(used) + 3)
            ]
            expected = allocated(used, candidates)
            actual = peri_scribe.kml.fire_data.unique_filename_prefix(
                None,
                name,
                frozenset(used),
            )
            assert actual == expected
            used.add(actual)


def report(names: tuple[str, ...]) -> peri_scribe.report.gathering.FireReport:
    """Use separate identities even when displayed headings collapse to one slug.

    Args:
        names: Display names in source and detail order.

    Returns:
        Repeated section membership backed by exactly one detail per identity.
    """
    entries = tuple(
        tests.helpers.factories.peri_scribe.report.markdown.make_entry(
            name,
            identifier=f"owner-{index}",
        )
        for index, name in enumerate(names)
    )
    return peri_scribe.report.gathering.FireReport(
        new_notable_fires=entries[::2],
        type_one_fires=entries[1::2],
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=entries,
        fire_details=entries,
    )


def check_markdown(directory: pathlib.Path, names: tuple[str, ...]) -> None:
    """Render the saved Markdown and resolve actual HTML IDs to owning detail bodies.

    Args:
        directory: Isolated year directory used by the real report writer.
        names: Distinct identities' possibly colliding displayed headings.
    """
    prepared = report(names)
    path = peri_scribe.report.markdown.render_markdown_report(prepared, directory)
    text = path.read_text()
    rendered = markdown_it.MarkdownIt().enable("table").render(text)
    document = lxml.html.fromstring(rendered)
    pairs = tests.formal.helpers.oracle.evaluate(
        [f"rings 0 | {len(names)}"],
        executable="oracleOutputs",
    )[0]
    expected = [f"fire-detail:{index}" for index in pairs[1::2]]
    anchors = document.xpath("//*[@id]")
    targets = [anchor.get("id") for anchor in anchors]
    assert targets == expected
    assert len(set(targets)) == len(targets)
    links = document.xpath("//a[starts-with(@href, '#')]/@href")
    assert links == [
        f"#{target}" for target in expected[::2] + expected[1::2] + expected
    ]
    for owner, anchor in enumerate(anchors):
        table = anchor.xpath("following::table[1]")
        assert len(table) == 1
        body = table[0].text_content()
        assert f"owner-{owner}" in body
        assert all(
            f"owner-{other}" not in body
            for other in range(len(names))
            if other != owner
        )


def closure(
    resources: list[tuple[str, int]],
    references: list[tuple[str, int]],
) -> bool:
    """Ask Lean to check exact resource ownership after parsing a real artifact.

    Args:
        resources: Defined names and their independently expected source owners.
        references: Parsed reference names and the owners of their referring features.

    Returns:
        Whether every reference has its exact name and owner in the registry.
    """
    names = sorted({name for name, _ in resources + references})
    positions = {name: index for index, name in enumerate(names)}
    sections = [
        " ".join(f"{positions[name]},{owner}" for name, owner in entries)
        for entries in (resources, references)
    ]
    result = tests.formal.helpers.oracle.evaluate(
        ["closed | " + " | ".join(sections)],
        executable="oracleOutputs",
    )[0]
    return result == (1,)
