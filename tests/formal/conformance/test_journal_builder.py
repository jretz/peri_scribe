from __future__ import annotations

import base64
import datetime
import io
import pathlib
import typing
import zipfile

import PIL.Image

import peri_scribe.kml.icons
import peri_scribe.kml.styles
import peri_scribe.paths
import peri_scribe.publication
import peri_scribe.updates
import tests.formal.helpers.journal
import tests.formal.helpers.journal_builder


if typing.TYPE_CHECKING:
    import pytest


def test_install_keeps_valid_image_payloads_in_real_publications(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = tests.formal.helpers.journal_builder.Scenario(
        directory=tmp_path / "2026",
        allowed=None,
    )
    tests.formal.helpers.journal_builder.install(monkeypatch, scenario)
    tests.formal.helpers.journal_builder.build(
        scenario,
        tests.formal.helpers.journal.EPOCH + datetime.timedelta(seconds=1),
        fresh=True,
    )
    with zipfile.ZipFile(peri_scribe.paths.kmz_path(scenario.directory)) as archive:
        names = {
            peri_scribe.kml.icons.interior_progression_icon_filename(),
            peri_scribe.kml.icons.perimeters_icon_filename(),
            *(
                peri_scribe.kml.icons.outlined_perimeter_icon_filename(color)
                for color in peri_scribe.kml.styles.OUTLINED_PERIMETER_COLORS
            ),
        }
        assert set(archive.namelist()) == {"doc.kml", *names}
        for name in names:
            with PIL.Image.open(io.BytesIO(archive.read(name))) as image:
                image.load()
                assert image.format == "PNG"
    snapshot = peri_scribe.publication.read_state(
        scenario.directory / "maps" / "updates.json",
        peri_scribe.updates.Snapshot,
    )
    assert snapshot is not None
    assert len(snapshot.updates) == (
        tests.formal.helpers.journal_builder.RECORDS_PER_GENERATION
    )
    for update in snapshot.updates:
        assert update.preview is not None
        prefix, encoded = update.preview.split(",", maxsplit=1)
        assert prefix == "data:image/webp;base64"
        with PIL.Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
            image.load()
            assert image.format == "WEBP"
