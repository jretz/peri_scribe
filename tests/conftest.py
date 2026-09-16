"""Configure shared pytest fixtures and isolate structured logging."""

from __future__ import annotations

import json
import pathlib
import typing
import warnings

import pytest
import structlog

import peri_scribe.logging


pytest_plugins = [
    "tests.helpers.fixtures.arcgis",
    "tests.helpers.fixtures.peri_scribe.fires.history",
    "tests.helpers.fixtures.peri_scribe.fires.incident_history",
    "tests.helpers.fixtures.peri_scribe.fires.reuse",
    "tests.helpers.fixtures.peri_scribe.fires.scores",
    "tests.helpers.fixtures.peri_scribe.fires.sources",
    "tests.helpers.fixtures.peri_scribe.geo.reading",
    "tests.helpers.fixtures.peri_scribe.kml.fire_data",
    "tests.helpers.fixtures.peri_scribe.kml.plot_data",
    "tests.helpers.fixtures.peri_scribe.kml.styles",
    "tests.helpers.fixtures.peri_scribe.logging",
    "tests.helpers.fixtures.peri_scribe.main",
    "tests.helpers.fixtures.peri_scribe.monitor.application",
    "tests.helpers.fixtures.peri_scribe.main_publication",
    "tests.helpers.fixtures.peri_scribe.models",
    "tests.helpers.fixtures.peri_scribe.perimeters.classification_data",
    "tests.helpers.fixtures.peri_scribe.perimeters.versions",
    "tests.helpers.fixtures.peri_scribe.snapshot_storage",
    "tests.helpers.fixtures.peri_scribe.sources.feeds",
    "tests.helpers.fixtures.peri_scribe.sources.fetching",
]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep generated examples from satisfying the source coverage requirement.

    Args:
        items: Collected tests to classify by their location.
    """
    property_based_directory = (
        pathlib.Path(__file__).resolve().parent / "tests" / "property_based"
    )
    marked_files: set[pathlib.Path] = set()
    for item in items:
        if item.path.is_relative_to(property_based_directory):
            item.add_marker(pytest.mark.no_cover)
            marked_files.add(item.path)
    if not marked_files:
        warnings.warn(
            f"No test files were marked no_cover under {property_based_directory}",
            category=pytest.PytestWarning,
            stacklevel=2,
        )


@pytest.fixture
def log_output() -> typing.Iterator[structlog.testing.LogCapture]:
    """Ensure captured log values can be serialized without a custom JSON encoder.

    Yields:
        An object that can be used to inspect captured log entries.
    """
    captured = structlog.testing.LogCapture()
    yield captured
    json.dumps(captured.entries, allow_nan=False)


@pytest.fixture(autouse=True)  # ruff: ignore[pytest-fixture-autouse]
def configure_structlog(
    log_output: structlog.testing.LogCapture,
) -> typing.Iterator[None]:
    """Isolate logging configuration and capture JSON-compatible log entries.

    Args:
        log_output: Captured structured log entries for assertions.

    Yields:
        Control while the test uses its own logging configuration.
    """
    original_configuration = structlog.get_config()
    structlog.configure(
        processors=[
            peri_scribe.logging.serialize_log_values,
            structlog.processors.format_exc_info,
            log_output,
        ],
        wrapper_class=structlog.make_filtering_bound_logger("DEBUG"),
    )
    try:
        yield
    finally:
        structlog.configure(**original_configuration)
