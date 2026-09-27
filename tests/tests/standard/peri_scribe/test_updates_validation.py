"""Publishing cannot replace the viewer after losing its ownership checkpoint."""

import pathlib

import pydantic
import pytest

import peri_scribe.fire_updates
import peri_scribe.updates
import tests.helpers.factories.peri_scribe.durable_updates


def test_write_updates_page_rejects_invalid_checkpoint_without_publishing(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.durable_updates.write(
        peri_scribe.fire_updates.state_path(tmp_path),
        b"{",
    )
    tests.helpers.factories.peri_scribe.durable_updates.write(
        tmp_path / "maps" / "updates.json",
        b"retained snapshot",
    )
    before = tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path)

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.updates.write_updates_page(tmp_path)

    assert (
        tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path) == before
    )
