"""Publication sharing never survives its owning execution."""

import pytest

import peri_scribe.execution


def test_get_without_execution_does_not_retain_values() -> None:
    peri_scribe.execution.put(peri_scribe.execution.Group.SOURCES, "input", object())
    assert not peri_scribe.execution.active()
    assert (
        peri_scribe.execution.get(peri_scribe.execution.Group.SOURCES, "input") is None
    )
    peri_scribe.execution.clear(peri_scribe.execution.Group.SOURCES)


def test_sharing_restores_outer_execution_after_exception() -> None:
    value = object()
    with peri_scribe.execution.sharing():
        peri_scribe.execution.put(peri_scribe.execution.Group.SOURCES, "input", value)
        with peri_scribe.execution.sharing():
            assert peri_scribe.execution.active()
            assert (
                peri_scribe.execution.get(peri_scribe.execution.Group.SOURCES, "input")
                is None
            )
        error = ValueError("interrupted")
        with (
            pytest.raises(ValueError, match="interrupted"),
            peri_scribe.execution.sharing(),
        ):
            raise error
        assert (
            peri_scribe.execution.get(peri_scribe.execution.Group.SOURCES, "input")
            is value
        )
    assert not peri_scribe.execution.active()


def test_clear_releases_only_finished_group() -> None:
    value = object()
    with peri_scribe.execution.sharing():
        for group in peri_scribe.execution.Group:
            peri_scribe.execution.put(group, "input", value)
        peri_scribe.execution.clear(peri_scribe.execution.Group.SOURCES)
        assert (
            peri_scribe.execution.get(peri_scribe.execution.Group.SOURCES, "input")
            is None
        )
        assert (
            peri_scribe.execution.get(peri_scribe.execution.Group.DERIVED, "input")
            is value
        )
