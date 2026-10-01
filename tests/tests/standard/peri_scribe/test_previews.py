"""Check lossless WebP payloads and disposable reuse of complete rendering inputs."""

import base64
import dataclasses
import io
import pathlib

import numpy as np
import PIL.Image
import pytest
import shapely

import peri_scribe.presentation.preview_geometry
import peri_scribe.presentation.preview_palette
import peri_scribe.previews
import spatial_data.product_cache
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.previews


def test_encode_webp_preserves_every_quantized_rgba_pixel() -> None:
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    image = peri_scribe.presentation.preview_geometry.draw_map(
        [(fire.perimeters[-1].geometry, "#4488bb")],
        [perimeter.geometry for perimeter in fire.perimeters],
    )
    quantized = peri_scribe.presentation.preview_palette.quantize(image)
    content = peri_scribe.previews.encode_webp(quantized.image)
    assert content[12:16] == b"VP8L"
    with PIL.Image.open(io.BytesIO(content)) as decoded:
        assert decoded.size == (128, 72)
        assert decoded.convert("RGBA").tobytes() == quantized.image.tobytes()
        assert (
            len(np.unique(np.asarray(decoded).reshape(-1, 4), axis=0))
            <= peri_scribe.presentation.preview_palette.COLOR_LIMIT
        )


def test_fire_preview_uses_latest_three_outlines_and_all_kmz_ring_fills() -> None:
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    first = peri_scribe.previews.fire_preview(fire)
    extra_old = dataclasses.replace(
        fire.perimeters[0],
        geometry=shapely.box(-130, 30, -129, 31),
    )
    second = peri_scribe.previews.fire_preview(
        dataclasses.replace(fire, perimeters=(extra_old, *fire.perimeters)),
    )
    assert second == first
    assert first is not None
    content = base64.b64decode(
        first.removeprefix(peri_scribe.previews.DATA_URL_PREFIX),
        validate=True,
    )
    with PIL.Image.open(io.BytesIO(content)) as image:
        assert image.size == (128, 72)
        bounds = image.getchannel("A").getbbox()
        assert bounds is not None
        assert bounds[1] == 0
        assert bounds[2] == image.width


def test_fire_preview_omits_missing_or_nondrawable_perimeters() -> None:
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    assert (
        peri_scribe.previews.fire_preview(
            dataclasses.replace(fire, perimeters=()),
        )
        is None
    )
    assert (
        peri_scribe.previews.fire_preview(
            dataclasses.replace(
                fire,
                perimeters=(
                    dataclasses.replace(
                        fire.perimeters[0],
                        geometry=shapely.Point(0, 0),
                    ),
                ),
            ),
        )
        is None
    )


def test_fire_preview_reuses_cached_image_and_invalidates_changed_geometry(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    database = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(database, "test"):
        first = peri_scribe.previews.fire_preview(fire)
    with monkeypatch.context() as patch:
        patch.setattr(
            peri_scribe.presentation.preview_geometry,
            "draw_map",
            tests.helpers.doubles.errors.raising_stub(
                AssertionError("Repeated drawing"),
            ),
        )
        with spatial_data.product_cache.scope(database, "test"):
            assert (
                peri_scribe.previews.fire_preview(
                    dataclasses.replace(fire, name="Renamed"),
                )
                == first
            )
    changed = dataclasses.replace(fire, progression_rings=())
    with spatial_data.product_cache.scope(database, "test"):
        assert peri_scribe.previews.fire_preview(changed) != first
    with spatial_data.product_cache.scope(database, "different-runtime"):
        assert peri_scribe.previews.fire_preview(changed) is not None


@pytest.mark.parametrize(
    ("format_name", "size"),
    [("PNG", (128, 72)), ("WEBP", (1, 1))],
)
def test_cached_content_rejects_wrong_format_or_dimensions(
    tmp_path: pathlib.Path,
    format_name: str,
    size: tuple[int, int],
) -> None:
    stream = io.BytesIO()
    PIL.Image.new("RGBA", size).save(stream, format=format_name)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        spatial_data.product_cache.put(
            peri_scribe.previews.NAMESPACE,
            "key",
            stream.getvalue(),
        )
        assert peri_scribe.previews.cached_content("key") is None


def test_cached_content_rejects_malformed_images(tmp_path: pathlib.Path) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        spatial_data.product_cache.put(
            peri_scribe.previews.NAMESPACE,
            "key",
            b"incomplete WebP",
        )
        assert peri_scribe.previews.cached_content("key") is None
