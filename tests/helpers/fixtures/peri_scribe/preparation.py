"""Opt selected geography tests into exact fixed-environment observation sharing."""

import collections.abc

import pytest

import peri_scribe.fires.reuse
import peri_scribe.preparation
import tests.helpers.doubles.peri_scribe.preparation_environment


@pytest.fixture(scope="session")
def preparation_environment_observations() -> collections.abc.Iterator[
    tests.helpers.doubles.peri_scribe.preparation_environment.Observations
]:
    """Keep native results inside one worker and verify its unchanged environment.

    Yields:
        Exact immutable fingerprint strings retained from the original functions.
    """
    observations = (
        tests.helpers.doubles.peri_scribe.preparation_environment.observations()
    )
    yield observations
    observations.verify()


@pytest.fixture
def reuse_preparation_environment(
    monkeypatch: pytest.MonkeyPatch,
    preparation_environment_observations: (
        tests.helpers.doubles.peri_scribe.preparation_environment.Observations
    ),
) -> None:
    """Share environment reads while each test owns its data and current settings.

    Args:
        monkeypatch: Restore native functions when this selected test finishes.
        preparation_environment_observations: This worker's sealed native observations.
    """
    monkeypatch.setattr(
        peri_scribe.preparation,
        "runtime_fingerprint",
        preparation_environment_observations.fingerprint,
    )
    monkeypatch.setattr(
        peri_scribe.fires.reuse,
        "derivation_context",
        preparation_environment_observations.context,
    )
