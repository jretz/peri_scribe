"""Terminate real city database writes without executing Python cleanup."""

import dataclasses
import io
import json
import os
import pathlib
import sys

import pydantic
import pytest
import requests

import peri_scribe.sources.catalog
import peri_scribe.sources.cities
import tests.formal.helpers.conditional_download
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.sources.cities


EXIT_STATUS = 73


class Terminate(BaseException):
    """Exit during exception construction so no handler or finally block executes."""

    def __init__(self) -> None:
        """Make the observed process exit independent of cleanup behavior."""
        os._exit(EXIT_STATUS)


def crash(directory: pathlib.Path, *, existing: str, boundary: str) -> None:
    """Retain the actual trace and files across a hard process exit.

    Args:
        directory: Private storage containing the checked graph and execution files.
        existing: Whether the invocation starts with absent or valid SQLite data.
        boundary: Partial conversion, validated staging, or published replacement.
    """
    graph = pydantic.TypeAdapter(tests.formal.helpers.tlc.Graph).validate_json(
        (directory / "graph.json").read_bytes(),
    )
    trace = directory / "trace.jsonl"
    original_transition = tests.formal.helpers.conditional_download.Observer.transition

    def observe(
        observer: tests.formal.helpers.conditional_download.Observer,
        action: str,
        projection: tests.formal.helpers.conditional_download.Projection,
    ) -> None:
        """Flush every concrete boundary before independently terminating the process.

        Args:
            observer: Matcher retaining the complete execution prefix.
            action: The actual production boundary just observed.
            projection: Observed conversion state combined with published file bytes.
        """
        with trace.open("a") as stream:
            if observer.path.observations == 1:
                stream.write(
                    json.dumps({
                        "action": "start",
                        "value": dataclasses.asdict(
                            observer.path.value,
                        ),
                    })
                    + "\n",
                )
            original_transition(observer, action, projection)
            stream.write(
                json.dumps({
                    "action": action,
                    "value": dataclasses.asdict(
                        observer.path.value,
                    ),
                })
                + "\n",
            )
        if boundary == "published" and action == "Publish":
            os._exit(EXIT_STATUS)

    scenarios = {
        "partial": (
            tests.formal.helpers.conditional_download.Scenario.INTERRUPT_CONVERSION
        ),
        "validated": (
            tests.formal.helpers.conditional_download.Scenario.INTERRUPT_PUBLISH
        ),
        "published": tests.formal.helpers.conditional_download.Scenario.FRESH,
    }
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            tests.formal.helpers.conditional_download.Observer,
            "transition",
            observe,
        )
        monkeypatch.setattr(
            tests.formal.helpers.conditional_download,
            "Interrupted",
            Terminate,
        )
        try:
            tests.formal.helpers.conditional_download.replay(
                graph,
                directory / "year",
                monkeypatch,
                existing=existing,
                validators="etag",
                scenario=scenarios[boundary],
            )
        finally:
            (directory / "finally-ran").touch()


def recover(directory: pathlib.Path) -> None:
    """A fresh interpreter must reuse complete output and rebuild absent output.

    Args:
        directory: Retained files from the independently terminated writer.
    """
    year = directory / "year"
    source = peri_scribe.sources.catalog.CITIES_SOURCE
    path = peri_scribe.sources.cities.city_database_path(year)
    previous = peri_scribe.sources.cities.read_database(path, source.url)
    observed_headers: dict[str, str] = {}

    def get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> requests.Response:
        """The recovery response must depend on the actual retained database.

        Args:
            url: Requested source URL.
            headers: Actual validator supplied by the recovered generation.
            timeout: Production request timeout.

        Returns:
            A 304 for existing usable output or complete content for absent output.
        """
        assert url == source.url
        assert timeout > 0
        observed_headers.update(headers)
        response = requests.Response()
        response.status_code = 304 if previous is not None else 200
        response.raw = io.BytesIO(b"recovered source archive")
        response.headers["ETag"] = '"recovered"'
        return response

    def archive(
        content: bytes,
    ) -> tuple[str, tuple[peri_scribe.sources.cities.City, ...]]:
        """Keep recovered SQLite construction real while substituting source decoding.

        Args:
            content: The actual upstream bytes consumed by the production reader.

        Returns:
            A fresh recovery generation.
        """
        assert content == b"recovered source archive"
        return "5.1.2", (
            tests.helpers.factories.peri_scribe.sources.cities.city(
                name="Recovered Place",
            ),
        )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(requests, "get", get)
        monkeypatch.setattr(peri_scribe.sources.cities, "archive_cities", archive)
        peri_scribe.sources.cities.fetch_cities_database(source, year)
    recovered = peri_scribe.sources.cities.load_database(path, source.url)
    print(
        json.dumps({
            "previous": None if previous is None else previous.cities[0].name,
            "recovered": recovered.cities[0].name,
            "headers": observed_headers,
        }),
    )


def main() -> None:
    """Keep all subprocess requests within their parent's private test directory."""
    request = json.load(sys.stdin)
    directory = pathlib.Path(request["directory"])
    if request["operation"] == "crash":
        crash(directory, existing=request["existing"], boundary=request["boundary"])
    else:
        assert request["operation"] == "recover"
        recover(directory)


if __name__ == "__main__":
    main()
