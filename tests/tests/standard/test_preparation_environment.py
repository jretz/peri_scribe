"""Shared test observations retain changing inputs and reject an invalid environment."""

import dataclasses
import importlib.metadata
import pathlib

import pytest
import shapely

import peri_scribe.fires.reuse
import peri_scribe.perimeters.cleaning
import peri_scribe.perimeters.size_filtering
import peri_scribe.preparation
import peri_scribe.sources.administrative_boundaries
import tests.helpers.doubles.peri_scribe.preparation_environment


def test_observations_verify_rejects_source_edits_at_the_same_size(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = pathlib.Path(peri_scribe.preparation.__file__).parents[1]
    dependency = root / "document_text" / "__init__.py"
    replacement = tmp_path / "dependency.py"
    replacement.write_text("# first\n")
    original_open = pathlib.Path.open
    monkeypatch.setattr(
        pathlib.Path,
        "open",
        lambda path, *args, **kwargs: original_open(
            replacement if path == dependency else path,
            *args,
            **kwargs,
        ),
    )
    observations = (
        tests.helpers.doubles.peri_scribe.preparation_environment.observations()
    )
    observations.verify()
    replacement.write_text("# other\n")
    with pytest.raises(AssertionError):
        observations.verify()


def test_observations_fingerprint_observes_runtime_changes_and_rejects_broken_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = (
        tests.helpers.doubles.peri_scribe.preparation_environment.observations()
    )
    before = observations.fingerprint()
    monkeypatch.setattr(shapely, "geos_version_string", "different native library")
    assert observations.fingerprint() == peri_scribe.preparation.runtime_fingerprint()
    assert observations.fingerprint() != before
    with pytest.raises(AssertionError):
        observations.verify()


def test_observations_context_rechecks_boundary_bytes_and_removal(
    tmp_path: pathlib.Path,
) -> None:
    observations = (
        tests.helpers.doubles.peri_scribe.preparation_environment.observations()
    )
    missing = observations.context(tmp_path)
    boundary = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        tmp_path,
    )
    boundary.parent.mkdir(parents=True)
    seen = {missing}
    for contents in (b"boundary one", b"boundary two"):
        boundary.write_bytes(contents)
        result = observations.context(tmp_path)
        assert result == peri_scribe.fires.reuse.derivation_context(tmp_path)
        assert result not in seen
        seen.add(result)
    boundary.unlink()
    assert observations.context(tmp_path) == missing
    observations.verify()


def test_observations_context_rechecks_configurations_and_cache_version(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = (
        tests.helpers.doubles.peri_scribe.preparation_environment.observations()
    )
    original = observations.context(tmp_path)
    cleaning = peri_scribe.perimeters.cleaning.DEFAULT_CLEANING_CONFIG
    changes = (
        (
            peri_scribe.perimeters.cleaning,
            "DEFAULT_CLEANING_CONFIG",
            dataclasses.replace(
                cleaning,
                maximum_deviation=cleaning.maximum_deviation * 2,
            ),
        ),
        (
            peri_scribe.perimeters.size_filtering,
            "DEFAULT_SIZE_FILTER_CONFIG",
            dataclasses.replace(
                peri_scribe.perimeters.size_filtering.DEFAULT_SIZE_FILTER_CONFIG,
                minimum_computed_area_fraction=0.3,
            ),
        ),
        (peri_scribe.fires.reuse, "CACHE_VERSION", 100),
    )
    for module, attribute, value in changes:
        with monkeypatch.context() as changed:
            changed.setattr(module, attribute, value)
            result = observations.context(tmp_path)
            assert result == peri_scribe.fires.reuse.derivation_context(tmp_path)
            assert result != original
        assert observations.context(tmp_path) == original
    observations.verify()


def test_observations_fingerprint_uses_native_replaced_package_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = (
        tests.helpers.doubles.peri_scribe.preparation_environment.observations()
    )
    original = observations.fingerprint()
    version = importlib.metadata.version
    with monkeypatch.context() as changed:
        changed.setattr(
            importlib.metadata,
            "version",
            lambda name: "different" if name == "shapely" else version(name),
        )
        assert (
            observations.fingerprint() == peri_scribe.preparation.runtime_fingerprint()
        )
        assert observations.fingerprint() != original
    assert observations.fingerprint() == original
    observations.verify()
