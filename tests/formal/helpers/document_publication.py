"""Compare actual document visibility at write boundaries with checked TLC states."""

import dataclasses
import enum
import itertools
import json
import pathlib
import typing

import pytest

import peri_scribe.models
import peri_scribe.output
import peri_scribe.paths
import peri_scribe.report.gathering
import peri_scribe.report.markdown
import tests.helpers.doubles.peri_scribe.document_publication
import tests.helpers.factories.peri_scribe.output


BEFORE_REPLACE = 4
AFTER_REPLACE = 5


class Document(enum.StrEnum):
    """Each public entry point must inherit the publication guarantee."""

    INDEX = "index"
    SCORES = "scores"
    HTML = "html"
    MARKDOWN = "markdown"


def publish(directory: pathlib.Path, kind: Document) -> pathlib.Path:
    """Exercise production serialization and path selection.

    Args:
        directory: Isolated year directory.
        kind: Public writer to exercise.

    Returns:
        Its canonical output path.
    """
    directory.mkdir(parents=True, exist_ok=True)
    match kind:
        case Document.INDEX:
            path = directory / "index.json"
            peri_scribe.output.write_document(
                path,
                peri_scribe.models.FireIndex(version="new", fires=[]),
            )
        case Document.SCORES:
            path = directory / "scores.json"
            peri_scribe.output.write_document(
                path,
                tests.helpers.factories.peri_scribe.output.fire_scores_document([12]),
            )
        case Document.HTML:
            path = directory / "scores.html"
            peri_scribe.output.write_fire_scores_ccdf(
                path,
                tests.helpers.factories.peri_scribe.output.fire_scores_document([12]),
            )
        case Document.MARKDOWN:
            path = peri_scribe.report.markdown.render_markdown_report(
                peri_scribe.report.gathering.FireReport(
                    new_notable_fires=(),
                    type_one_fires=(),
                    fastest_growing_by_acres=(),
                    fastest_growing_by_percent=(),
                    top_fires=(),
                    fire_details=(),
                ),
                directory,
            )
    return path


@dataclasses.dataclass(kw_only=True)
class PublicationProbe:
    """Capture observable file contents while replacing only low-level write timing."""

    path: pathlib.Path
    original: str | None
    expected: str
    interrupt: int | None
    checked: set[tuple[int, int, int, str]]
    observations: list[int] = dataclasses.field(default_factory=list)

    def observe(self, phase: str, chunks: int) -> None:
        """Require each intermediate canonical file to match a checked projection.

        Args:
            phase: Corresponding model phase.
            chunks: Number of completed private chunks.
        """
        contents = self.path.read_text(encoding="utf-8") if self.path.exists() else None
        generation = {None: 0, self.original: int(self.original is not None)}.get(
            contents,
        )
        if contents == self.expected:
            generation = 2
        assert generation is not None, "Reader observed truncated published contents"
        assert (
            int(self.original is not None),
            generation,
            chunks,
            phase,
        ) in self.checked
        self.observations.append(generation)

    def write_chunks(self, stream: typing.TextIO, text: str) -> None:
        """Expose physical write boundaries to readers and interruption.

        Args:
            stream: The real file opened by production code.
            text: Exact serialized contents.

        Raises:
            ProcessLoss: The configured partial write completed.
        """
        for chunk in range(4):
            if chunk:
                stream.write(
                    text[len(text) * (chunk - 1) // 3 : len(text) * chunk // 3],
                )
                stream.flush()
            self.observe("write", chunk)
            if self.interrupt == chunk:
                raise tests.helpers.doubles.peri_scribe.document_publication.ProcessLoss

    def dump_json(
        self,
        document: object,
        stream: typing.TextIO,
        *,
        indent: int,
    ) -> None:
        """Keep real JSON encoding while controlling partial file writes.

        Args:
            document: Production-selected JSON object.
            stream: Production-selected file.
            indent: Production-selected indentation.
        """
        self.write_chunks(stream, json.dumps(document, indent=indent))

    def install(self, patch: pytest.MonkeyPatch) -> None:
        """Inspect files before and after the operating-system replacement.

        Args:
            patch: Isolated patch context.
        """
        original_replace = pathlib.Path.replace

        def write_text(path: pathlib.Path, text: str, *, encoding: str) -> int:
            """Retain the actual destination and encoding chosen by the text writer.

            Args:
                path: Production staging path.
                text: Exact output.
                encoding: Output encoding.

            Returns:
                Number of written characters on success.
            """
            with path.open("w", encoding=encoding) as stream:
                self.write_chunks(stream, text)
            return len(text)

        def replace(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
            """Observe both sides of the canonical name's atomic replacement.

            Args:
                path: Complete staging file.
                target: Public destination.

            Returns:
                The published path.

            Raises:
                ProcessLoss: The configured replacement boundary was reached.
            """
            assert target == self.path
            assert path.parent.parent == self.path.parent
            assert path.read_text(encoding="utf-8") == self.expected
            self.observe("replace", 3)
            if self.interrupt == BEFORE_REPLACE:
                raise tests.helpers.doubles.peri_scribe.document_publication.ProcessLoss
            result = original_replace(path, target)
            self.observe("done", 3)
            if self.interrupt == AFTER_REPLACE:
                raise tests.helpers.doubles.peri_scribe.document_publication.ProcessLoss
            return result

        patch.setattr(json, "dump", self.dump_json)
        patch.setattr(pathlib.Path, "write_text", write_text)
        patch.setattr(pathlib.Path, "replace", replace)


def replay(states: list[dict[str, str]], directory: pathlib.Path) -> int:
    """Fault every serialization boundary for all public document writers.

    Args:
        states: Entire checked TLC graph.
        directory: Isolated case directory.

    Returns:
        Number of concrete interrupted/successful publication scenarios.
    """
    checked = {
        (
            int(state["prior"]),
            int(state["published"]),
            int(state["staged"]),
            state["phase"].strip('"'),
        )
        for state in states
    }
    count = 0
    for kind in Document:
        template = publish(directory / "templates" / kind / "2026", kind)
        expected = template.read_text(encoding="utf-8")
        for original, interruption in itertools.product(
            (None, "Previous complete document\n"),
            (*range(6), None),
        ):
            year = directory / str(count) / "2026"
            relative = template.relative_to(template.parent)
            path = (
                peri_scribe.paths.markdown_report_path(year)
                if kind == Document.MARKDOWN
                else year / relative
            )
            path.parent.mkdir(parents=True)
            if original is not None:
                path.write_text(original, encoding="utf-8")
            probe = PublicationProbe(
                path=path,
                original=original,
                expected=expected,
                interrupt=interruption,
                checked=checked,
            )
            with pytest.MonkeyPatch.context() as patch:
                probe.install(patch)
                if interruption is None:
                    publish(year, kind)
                else:
                    with pytest.raises(
                        tests.helpers.doubles.peri_scribe.document_publication.ProcessLoss,
                    ):
                        publish(year, kind)
            assert probe.observations
            if interruption in {5, None}:
                assert path.read_text(encoding="utf-8") == expected
            elif original is None:
                assert not path.exists()
            else:
                assert path.read_text(encoding="utf-8") == original
            assert list(path.parent.iterdir()) == ([path] if path.exists() else [])
            publish(year, kind)
            assert path.read_text(encoding="utf-8") == expected
            count += 1
    return count
