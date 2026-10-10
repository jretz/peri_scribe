"""Bind city database refresh observations to one complete checked execution."""

import dataclasses
import enum
import io
import pathlib
import typing

import requests

import peri_scribe.exceptions
import peri_scribe.sources.catalog
import peri_scribe.sources.cities
import tests.formal.helpers.paths
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.sources.cities


if typing.TYPE_CHECKING:
    import pytest


@dataclasses.dataclass(frozen=True, kw_only=True)
class Projection:
    """Observe publication separately from completed conversion and validation."""

    final: int
    request: str = "unset"
    staged: int = 0
    validated: bool = False
    outcome: str = "pending"


class Scenario(enum.StrEnum):
    """Keep each independently fallible boundary visible in the replay inventory."""

    FRESH = "fresh"
    NOT_MODIFIED = "not_modified"
    REQUEST_FAILURE = "request_failure"
    CONVERSION_FAILURE = "conversion_failure"
    VALIDATION_FAILURE = "validation_failure"
    REPLACE_FAILURE = "replace_failure"
    INTERRUPT_CONVERSION = "interrupt_conversion"
    INTERRUPT_PUBLISH = "interrupt_publish"


class Interrupted(BaseException):
    """Represent process interruption outside the source's exception fallback."""


@dataclasses.dataclass(kw_only=True)
class Observer:
    """Observe actual published bytes while retaining the complete abstract prefix."""

    path: tests.formal.helpers.paths.Path[Projection]
    destination: pathlib.Path
    original: bytes | None
    previous: bool

    def transition(self, action: str, projection: Projection) -> None:
        """A new visible generation must follow the preceding concrete boundaries.

        Args:
            action: The production boundary that just completed.
            projection: Nonpersistent observations of the production operation.
        """
        contents = self.destination.read_bytes() if self.destination.exists() else None
        final = int(self.previous) if contents == self.original else 2
        self.path = self.path.transition(
            action,
            dataclasses.replace(projection, final=final),
        )


def contract(
    graph: tests.formal.helpers.tlc.Graph,
    *,
    previous: bool,
    validators: str,
) -> tests.formal.helpers.paths.Contract[Projection]:
    """Keep the initial validator policy fixed throughout one refresh.

    Args:
        graph: Complete checked conditional-download graph.
        previous: Whether the invocation begins with a usable database.
        validators: Initial HTTP validators in that database.

    Returns:
        A matcher requiring explicit request, staging, and publication observations.
    """
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            node: Projection(
                final=int(state["final"]),
                request=state["request"].strip('"'),
                staged=int(state["staged"]),
                validated=state["validated"] == "TRUE",
                outcome=state["outcome"].strip('"'),
            )
            for node, state in graph.states.items()
            if (state["previous"] == "1") == previous
            and state["validators"].strip('"') == validators
        },
        actions={
            edge: edge.action for edges in graph.outgoing.values() for edge in edges
        },
        internal=frozenset(),
    )


def replay(
    graph: tests.formal.helpers.tlc.Graph,
    directory: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing: str,
    validators: str,
    scenario: Scenario,
) -> None:
    """Execute the real source protocol with independently observed durable boundaries.

    Args:
        graph: Checked transition graph for the complete refresh protocol.
        directory: Isolated storage for the previous and replacement databases.
        monkeypatch: Per-execution replacements for upstream and fault boundaries.
        existing: Absent, invalid, or usable previous SQLite database.
        validators: Validator combination to put in the previous metadata.
        scenario: HTTP result or selected exception/interruption boundary.
    """
    previous = existing == "valid"
    destination = peri_scribe.sources.cities.city_database_path(directory)
    destination.parent.mkdir(parents=True)
    if existing != "absent":
        database = tests.helpers.factories.peri_scribe.sources.cities.database(
            etag='"first"' if validators in {"etag", "both"} else None,
            last_modified="yesterday" if validators in {"modified", "both"} else None,
        )
        peri_scribe.sources.cities.write_database(destination, database)
        if not previous:
            destination.write_bytes(b"invalid SQLite file")
    checked = contract(graph, previous=previous, validators=validators)
    observer = Observer(
        path=checked.start(Projection(final=int(previous))),
        destination=destination,
        original=destination.read_bytes() if destination.exists() else None,
        previous=previous,
    )
    source = peri_scribe.sources.catalog.CITIES_SOURCE
    configure_transport(observer, scenario, monkeypatch)
    configure_storage(observer, scenario, monkeypatch)
    try:
        result = peri_scribe.sources.cities.fetch_cities_database(source, directory)
    except Interrupted:
        observer.transition(
            "Crash",
            dataclasses.replace(observer.path.value, outcome="interrupted"),
        )
    except peri_scribe.exceptions.ExternalDataError:
        observer.transition(
            "NotModified" if scenario == Scenario.NOT_MODIFIED else "Fail",
            dataclasses.replace(observer.path.value, outcome="fatal"),
        )
    else:
        assert result == (destination,)
        if observer.path.value.outcome != "fresh":
            observer.transition(
                "NotModified" if scenario == Scenario.NOT_MODIFIED else "Fail",
                dataclasses.replace(observer.path.value, outcome="cached"),
            )
    if scenario == Scenario.FRESH:
        expected = "fresh"
    elif scenario in {Scenario.INTERRUPT_CONVERSION, Scenario.INTERRUPT_PUBLISH}:
        expected = "interrupted"
    else:
        expected = "cached" if previous else "fatal"
    assert observer.path.value.outcome == expected


def configure_transport(
    observer: Observer,
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep upstream response selection separate from the real persistence operations.

    Args:
        observer: The continuously matched execution and its visible destination.
        scenario: Selected upstream outcome or later failure boundary.
        monkeypatch: Per-execution source replacements.
    """
    fresh = tests.helpers.factories.peri_scribe.sources.cities.city(name="New Place")

    def get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> requests.Response:
        """Expose actual HTTP headers rather than reproducing the selection policy.

        Args:
            url: Actual requested source URL.
            headers: Actual conditional request headers.
            timeout: Production request timeout.

        Returns:
            The selected complete or unmodified response.

        Raises:
            ConnectionError: For the injected network failure.
        """
        assert url == peri_scribe.sources.catalog.CITIES_SOURCE.url
        assert timeout > 0
        if headers == {"If-None-Match": '"first"'}:
            request = "etag"
        elif headers == {"If-Modified-Since": "yesterday"}:
            request = "modified"
        else:
            assert not headers
            request = "none"
        observer.transition(
            "Request",
            dataclasses.replace(observer.path.value, request=request),
        )
        if scenario == Scenario.REQUEST_FAILURE:
            message = "injected network failure"
            raise requests.ConnectionError(message)
        response = requests.Response()
        response.status_code = 304 if scenario == Scenario.NOT_MODIFIED else 200
        response.headers["ETag"] = '"second"'
        response.raw = io.BytesIO(b"new source archive")
        return response

    def archive(
        content: bytes,
    ) -> tuple[str, tuple[peri_scribe.sources.cities.City, ...]]:
        """Supply parsed locations while keeping SQLite creation and validation real.

        Args:
            content: Body actually read from the upstream response.

        Returns:
            A source version and fresh city record.
        """
        assert content == b"new source archive"
        observer.transition(
            "Download",
            dataclasses.replace(observer.path.value, staged=1),
        )
        return "5.1.2", (fresh,)

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(peri_scribe.sources.cities, "archive_cities", archive)


def configure_storage(
    observer: Observer,
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inject failures around actual conversion, validation, and replacement.

    Args:
        observer: The continuously matched execution and its visible destination.
        scenario: Selected ordinary exception or abrupt interruption boundary.
        monkeypatch: Per-execution storage wrappers.
    """
    original_write = peri_scribe.sources.cities.write_database
    original_load = peri_scribe.sources.cities.load_database
    original_replace = pathlib.Path.replace

    def write(
        path: pathlib.Path,
        database: peri_scribe.sources.cities.Database,
    ) -> None:
        """Fail or interrupt with actual partially written private staging bytes.

        Args:
            path: Private staging destination.
            database: Generation prepared by the production reader.

        Raises:
            Interrupted: At the selected conversion interruption.
            OSError: At the selected conversion failure.
        """
        if scenario in {Scenario.CONVERSION_FAILURE, Scenario.INTERRUPT_CONVERSION}:
            path.write_bytes(b"incomplete SQLite conversion")
            if scenario == Scenario.INTERRUPT_CONVERSION:
                raise Interrupted
            message = "injected conversion failure"
            raise OSError(message)
        original_write(path, database)
        observer.transition(
            "Convert",
            dataclasses.replace(observer.path.value, staged=2),
        )

    def load(path: pathlib.Path, url: str) -> peri_scribe.sources.cities.Database:
        """Observe successful staging validation independently from replacement.

        Args:
            path: Database being validated.
            url: Expected upstream source URL.

        Returns:
            The validated generation read from the actual SQLite file.

        Raises:
            ValueError: At the selected staging validation failure.
        """
        if path != observer.destination and scenario == Scenario.VALIDATION_FAILURE:
            message = "injected validation failure"
            raise ValueError(message)
        database = original_load(path, url)
        if path != observer.destination:
            observer.transition(
                "Validate",
                dataclasses.replace(observer.path.value, validated=True),
            )
        return database

    def replace(path: pathlib.Path, target: pathlib.Path | str) -> pathlib.Path:
        """Keep the real filesystem replacement as the publication boundary.

        Args:
            path: Fully converted and validated staging file.
            target: Published destination supplied by the production writer.

        Returns:
            The destination after real atomic replacement.

        Raises:
            Interrupted: At the selected pre-publication interruption.
            OSError: At the selected filesystem replacement failure.
        """
        assert pathlib.Path(target) == observer.destination
        if scenario == Scenario.INTERRUPT_PUBLISH:
            raise Interrupted
        if scenario == Scenario.REPLACE_FAILURE:
            message = "injected replacement failure"
            raise OSError(message)
        result = original_replace(path, target)
        observer.transition(
            "Publish",
            dataclasses.replace(observer.path.value, outcome="fresh"),
        )
        return result

    monkeypatch.setattr(peri_scribe.sources.cities, "write_database", write)
    monkeypatch.setattr(peri_scribe.sources.cities, "load_database", load)
    monkeypatch.setattr(pathlib.Path, "replace", replace)
