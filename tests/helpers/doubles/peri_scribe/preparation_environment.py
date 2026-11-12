"""Share exact environment observations in tests with fixed source and dependencies.

The input boundary and qualification are described in
[Testing](../../../../docs/testing.md#immutable-preparation-environments).
"""

from __future__ import annotations

import collections.abc
import dataclasses
import hashlib
import importlib.metadata
import json
import pathlib
import platform
import sys

import PIL.features
import pyproj
import shapely

import peri_scribe.fires.reuse
import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.cleaning
import peri_scribe.perimeters.size_filtering
import peri_scribe.preparation
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.authentication


PACKAGES = (
    "peri_scribe",
    "arcgis_access",
    "aircraft_registration",
    "document_text",
    "measurement_units",
    "spatial_data",
    "kml_io",
    "svg_charts",
)
LIBRARIES = (
    "shapely",
    "pyproj",
    "geopandas",
    "pyogrio",
    "pint",
    "pandas",
    "numpy",
    "pydantic",
    "pillow",
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Runtime:
    """Keep numerical and interpreter identities distinct from package versions."""

    python: str
    platform: str
    geos: str
    proj: str
    webp: str | None


@dataclasses.dataclass(frozen=True, kw_only=True)
class Environment:
    """Retain complete immutable inputs to the selected worker's environment reads."""

    sources: tuple[tuple[str, bytes], ...]
    libraries: tuple[tuple[str, str], ...]
    runtime: Runtime


@dataclasses.dataclass(frozen=True, kw_only=True)
class Derivation:
    """Keep every input that selected geography tests can change between calls."""

    runtime: Runtime
    boundary: str | None
    version: int
    cleaning: str
    size_filter: str
    classification: str


def runtime() -> Runtime:
    """Observe the current native versions even when source files remain fixed.

    Returns:
        The runtime fields used by the two production fingerprints.
    """
    return Runtime(
        python=sys.version,
        platform=platform.platform(),
        geos=shapely.geos_version_string,
        proj=pyproj.proj_version_str,
        webp=PIL.features.version_module("webp"),
    )


def environment() -> Environment:
    """Seal actual bytes and package versions at the worker's observation boundary.

    Returns:
        Complete source contents and dependencies for comparison after the tests.
    """
    root = pathlib.Path(peri_scribe.preparation.__file__).parents[1]
    return Environment(
        sources=tuple(
            (str(path.relative_to(root)), path.read_bytes())
            for package in PACKAGES
            for path in sorted((root / package).rglob("*.py"))
        ),
        libraries=tuple((name, importlib.metadata.version(name)) for name in LIBRARIES),
        runtime=runtime(),
    )


def primitive_bindings() -> tuple[object, ...]:
    """Let replacements of reviewed readers and encoders use their native behavior.

    Returns:
        Source locations and dependency bindings used by the original functions.
    """
    return (
        peri_scribe.preparation.__file__,
        peri_scribe.fires.reuse.__file__,
        importlib.metadata.version,
        platform.platform,
        hashlib.file_digest,
        hashlib.sha256,
        json.dumps,
        pathlib.Path.rglob,
        pathlib.Path.open,
        peri_scribe.fires.reuse.data_digest,
        peri_scribe.fires.reuse.file_digest,
        peri_scribe.sources.authentication.read_file_digest,
        peri_scribe.sources.administrative_boundaries.output_geopackage_path,
        peri_scribe.perimeters.classification_data.BorderClassificationConfig,
        PIL.features.version_module,
    )


def derivation(year_directory: pathlib.Path) -> Derivation:
    """Read boundary bytes and configuration on every geography request.

    Args:
        year_directory: The invocation's isolated source and derived data directory.

    Returns:
        Exact dynamic inputs to the native derivation fingerprint.
    """
    boundary = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        year_directory,
    )
    return Derivation(
        runtime=runtime(),
        boundary=(
            peri_scribe.fires.reuse.file_digest(boundary)
            if boundary.is_file()
            else None
        ),
        version=peri_scribe.fires.reuse.CACHE_VERSION,
        cleaning=repr(peri_scribe.perimeters.cleaning.DEFAULT_CLEANING_CONFIG),
        size_filter=repr(
            peri_scribe.perimeters.size_filtering.DEFAULT_SIZE_FILTER_CONFIG,
        ),
        classification=repr(
            peri_scribe.perimeters.classification_data.BorderClassificationConfig(),
        ),
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Observations:
    """Own lookup tables whose shared results are actual immutable native strings."""

    environment: Environment
    bindings: tuple[object, ...]
    native_fingerprint: collections.abc.Callable[[], str]
    native_context: collections.abc.Callable[[pathlib.Path], str]
    fingerprints: dict[Runtime, str] = dataclasses.field(default_factory=dict)
    contexts: dict[Derivation, str] = dataclasses.field(default_factory=dict)

    def fingerprint(self) -> str:
        """Retain one actual result per runtime within the sealed environment.

        Returns:
            The production fingerprint for these exact immutable inputs.
        """
        if primitive_bindings() != self.bindings:
            return self.native_fingerprint()
        key = runtime()
        result = self.fingerprints.get(key)
        if result is None:
            result = self.native_fingerprint()
            self.fingerprints[key] = result
        return result

    def context(self, year_directory: pathlib.Path) -> str:
        """Reuse a completed context only after observing its current dynamic inputs.

        Args:
            year_directory: The current test's independent year directory.

        Returns:
            The original context for the current boundary and configuration.
        """
        if primitive_bindings() != self.bindings:
            return self.native_context(year_directory)
        key = derivation(year_directory)
        result = self.contexts.get(key)
        if result is None:
            result = self.native_context(year_directory)
            self.contexts[key] = result
        return result

    def verify(self) -> None:
        """Reject a worker run whose supposedly fixed input environment changed."""
        assert primitive_bindings() == self.bindings
        assert environment() == self.environment


def observations() -> Observations:
    """Capture the original functions before the selected test installs its adapter.

    Returns:
        Private lookup tables and their complete source/runtime input seal.
    """
    return Observations(
        environment=environment(),
        bindings=primitive_bindings(),
        native_fingerprint=peri_scribe.preparation.runtime_fingerprint,
        native_context=peri_scribe.fires.reuse.derivation_context,
    )
