"""Bind disposable preparation to the publication's code and native runtime."""

from __future__ import annotations

import collections.abc
import contextlib
import functools
import hashlib
import importlib.metadata
import json
import pathlib
import platform
import sys
import typing

import pyproj
import shapely

import peri_scribe.execution
import spatial_data.product_cache


def unconditional_rebuild(*, requested: bool) -> bool:
    """Honor an owning publication's rebuild policy inside nested stage entrypoints.

    Args:
        requested: Whether this stage directly requested unconditional preparation.

    Returns:
        Whether either this stage or its owning scope requires recomputation.
    """
    existing = spatial_data.product_cache.CURRENT.get()
    return requested or (existing is not None and existing.unconditional)


def runtime_fingerprint() -> str:
    """Invalidate products when code, numerical libraries, or the native build changes.

    Returns:
        The complete preparation environment's SHA-256 fingerprint.
    """
    source_root = pathlib.Path(__file__).parents[1]
    code: list[tuple[str, str]] = []
    for package in (
        "peri_scribe",
        "arcgis_access",
        "measurement_units",
        "spatial_data",
        "kml_io",
        "svg_charts",
    ):
        for path in sorted((source_root / package).rglob("*.py")):
            with path.open("rb") as stream:
                code.append((
                    str(path.relative_to(source_root)),
                    hashlib.file_digest(stream, "sha256").hexdigest(),
                ))
    context = {
        "version": 1,
        "code": code,
        "python": sys.version,
        "platform": platform.platform(),
        "geos": shapely.geos_version_string,
        "proj": pyproj.proj_version_str,
        "libraries": {
            name: importlib.metadata.version(name)
            for name in (
                "shapely",
                "pyproj",
                "geopandas",
                "pyogrio",
                "pint",
                "pandas",
                "numpy",
                "pydantic",
            )
        },
    }
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


@contextlib.contextmanager
def scope(
    year_directory: pathlib.Path,
    *,
    unconditional: bool = False,
) -> collections.abc.Iterator[None]:
    """Let standalone stages and complete publications use the same validated products.

    Args:
        year_directory: The year owning these sources and disposable derived products.
        unconditional: Whether existing preparations must be bypassed.

    Yields:
        Control with bounded memory sharing and persistent product storage available.
    """
    path = (year_directory / "derived" / "prepared-products.sqlite").resolve()
    existing = spatial_data.product_cache.CURRENT.get()
    context = (
        existing.context
        if existing is not None and existing.path == path
        else runtime_fingerprint()
    )
    with (
        contextlib.nullcontext()
        if peri_scribe.execution.active()
        else peri_scribe.execution.sharing(),
        spatial_data.product_cache.scope(path, context, unconditional=unconditional),
    ):
        yield


def cached_year[**Parameters, Result](
    function: collections.abc.Callable[
        typing.Concatenate[pathlib.Path, Parameters],
        Result,
    ],
) -> collections.abc.Callable[typing.Concatenate[pathlib.Path, Parameters], Result]:
    """Keep filesystem scope at year-aware entrypoints rather than pure preparation.

    Args:
        function: A stage whose first argument is its year directory.

    Returns:
        The stage with disposable preparation managed for its entire invocation.
    """

    @functools.wraps(function)
    def wrapped(
        year_directory: pathlib.Path,
        *args: Parameters.args,
        **kwargs: Parameters.kwargs,
    ) -> Result:
        """Preserve the wrapped entrypoint's arguments, result, and failure behavior.

        Args:
            year_directory: The stage's source/output year.
            args: Additional positional arguments passed through to the stage.
            kwargs: Additional keyword arguments, including unconditional when present.

        Returns:
            The original stage's result.
        """
        with scope(year_directory, unconditional=bool(kwargs.get("unconditional"))):
            return function(year_directory, *args, **kwargs)

    return wrapped
