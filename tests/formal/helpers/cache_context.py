"""Exercise the enclosing runtime key that completes every persistent product key."""

import importlib.metadata
import pathlib
import platform
import sys

import pyproj
import pytest
import shapely

import peri_scribe.preparation
import tests.formal.helpers.cache_dependencies
import tests.formal.helpers.oracle


SOURCE_PACKAGES = (
    "peri_scribe",
    "arcgis_access",
    "aircraft_registration",
    "document_text",
    "measurement_units",
    "spatial_data",
    "kml_io",
    "svg_charts",
)
CONTRACT = tests.formal.helpers.cache_dependencies.Contract(
    namespace="preparation-context",
    consumed=(
        *SOURCE_PACKAGES,
        "python",
        "platform",
        "geos",
        "proj",
        "library",
    ),
)


def compare(directory: pathlib.Path, change: str) -> None:
    """Connect exact source/native dependency changes to Lean's key obligation.

    Args:
        directory: Isolated source tree for code-byte mutations.
        change: One declared source package or runtime component.
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        if change in SOURCE_PACKAGES:
            source = directory / "src"
            code = source / change / "module.py"
            code.parent.mkdir(parents=True)
            code.write_text("# first\n")
            monkeypatch.setattr(
                peri_scribe.preparation,
                "__file__",
                str(source / "peri_scribe" / "preparation.py"),
            )
        before = peri_scribe.preparation.runtime_fingerprint()
        match change:
            case "python":
                monkeypatch.setattr(sys, "version", "changed-runtime")
            case "platform":
                monkeypatch.setattr(platform, "platform", lambda: "changed-platform")
            case "geos":
                monkeypatch.setattr(shapely, "geos_version_string", "changed-geos")
            case "proj":
                monkeypatch.setattr(pyproj, "proj_version_str", "changed-proj")
            case "library":
                original = importlib.metadata.version
                monkeypatch.setattr(
                    importlib.metadata,
                    "version",
                    lambda name: (
                        "changed-version" if name == "pint" else original(name)
                    ),
                )
            case _:
                code = directory / "src" / change / "module.py"
                code.write_text("# other\n")
        after = peri_scribe.preparation.runtime_fingerprint()
    complete, same_key, same_dependencies = tests.formal.helpers.oracle.evaluate(
        [CONTRACT.command(change)],
        executable="oracleCache",
    )[0]
    assert complete == 1
    assert same_dependencies == same_key
    assert (before == after) == bool(same_key)
