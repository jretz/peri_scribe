"""Keep shared history inputs exact and reject changed rendering environments."""

import math
import pathlib
import unittest.mock

import pytest

import peri_scribe.presentation.preview_geometry
import tests.formal.helpers.session
import tests.helpers.factories.peri_scribe.presentation.preview_grid


def test_history_grid_preserves_binary64_angles_and_immutable_hull_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = tests.helpers.factories.peri_scribe.presentation.preview_grid
    geometry = peri_scribe.presentation.preview_geometry
    north = geometry.north_dart_hull(0.0)
    equal = geometry.shapely.from_wkb(north.wkb)
    upper = math.nextafter(geometry.MAXIMUM_ANGLE, -math.inf)
    original = (
        (geometry.MINIMUM_ANGLE, geometry.north_dart_hull(-math.pi / 2)),
        (-0.0, north),
        (0.0, north),
        (upper, geometry.north_dart_hull(math.radians(upper))),
        (math.nextafter(0.0, math.inf), equal),
    )
    monkeypatch.setattr(factory, "GRID_COUNT", len(original))
    encoded = factory.encode(original)
    restored = factory.decode(encoded)
    assert len(restored) == len(original) == factory.GRID_COUNT
    assert equal is not north
    assert encoded["indices"][1] == encoded["indices"][2] == encoded["indices"][-1]
    assert len(encoded["wkbs"]) == len({hull.wkb for _, hull in original})
    assert restored[1][1] is restored[2][1] is restored[-1][1]
    assert all(
        float(angle).hex() == float(saved).hex() and hull.wkb == expected.wkb
        for (angle, hull), (saved, expected) in zip(restored, original, strict=True)
    )


@pytest.mark.parametrize(
    "change",
    ["code", "defaults", "kwdefaults", "wrapped", "closure", "drawing"],
)
def test_history_grid_rejects_in_place_rendering_changes(
    change: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = tests.helpers.factories.peri_scribe.presentation.preview_grid
    geometry = peri_scribe.presentation.preview_geometry
    with tests.formal.helpers.session.temporary():
        grid = factory.current_grid()
        assert grid is not None
        assert grid.valid()
        render = geometry.supersampled_dart
        if change == "code":
            monkeypatch.setattr(render, "__code__", render.__code__.replace())
        elif change == "defaults":
            monkeypatch.setattr(render, "__defaults__", ())
        elif change == "kwdefaults":
            defaults = render.__kwdefaults__
            assert defaults is not None
            monkeypatch.setattr(render, "__kwdefaults__", dict(defaults))
        elif change == "wrapped":
            monkeypatch.setattr(geometry.north_dart_hull, "__wrapped__", render)
        elif change == "closure":
            closure = geometry.shapely.buffer.__closure__
            assert closure is not None
            monkeypatch.setattr(closure[0], "cell_contents", render)
        else:
            constructor = geometry.PIL.ImageDraw.ImageDraw.__init__
            monkeypatch.setattr(constructor, "__code__", constructor.__code__.replace())
        assert not grid.valid()


def test_history_grid_runs_native_body_after_constant_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = tests.helpers.factories.peri_scribe.presentation.preview_grid
    geometry = peri_scribe.presentation.preview_geometry
    with tests.formal.helpers.session.temporary():
        grid = factory.current_grid()
        assert grid is not None
        assert grid.valid()
        monkeypatch.setattr(geometry, "ANGLE_STEP", 180)
        result = grid.get()
        assert tuple(angle for angle, _ in result) == (
            geometry.MINIMUM_ANGLE,
            geometry.np.nextafter(geometry.MAXIMUM_ANGLE, -geometry.np.inf),
        )


@pytest.mark.parametrize("change", ["replacement", "code"])
def test_history_grid_rejects_coarse_changes_before_construction(
    change: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = tests.helpers.factories.peri_scribe.presentation.preview_grid
    geometry = peri_scribe.presentation.preview_geometry
    with tests.formal.helpers.session.temporary():
        assert factory.current_grid() is not None
        if change == "replacement":
            monkeypatch.setattr(geometry, "coarse_dart_hulls", geometry.north_dart_hull)
        else:
            loop = geometry.coarse_dart_hulls.__wrapped__
            monkeypatch.setattr(loop, "__code__", loop.__code__.replace())
        assert factory.current_grid() is None


def test_history_grid_requires_the_live_invocation_and_reviewed_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = tests.helpers.factories.peri_scribe.presentation.preview_grid
    with tests.formal.helpers.session.temporary():
        grid = factory.current_grid()
        assert grid is not None
        assert grid.valid()
        with monkeypatch.context() as changed:
            changed.setattr(factory, "RENDERER_DIGEST", "changed renderer")
            assert factory.current_grid() is None
            assert not grid.valid()
        assert grid.valid()
    assert not grid.valid()


@pytest.mark.parametrize("unchanged_metadata", [False, True])
def test_history_grid_rehashes_changed_renderer_artifacts(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    unchanged_metadata: bool,
) -> None:
    factory = tests.helpers.factories.peri_scribe.presentation.preview_grid
    artifact = tmp_path / "renderer.bin"
    artifact.write_bytes(b"first artifact")
    monkeypatch.setattr(factory, "ARTIFACTS", (artifact,))
    if unchanged_metadata:
        monkeypatch.setattr(
            pathlib.Path,
            "stat",
            unittest.mock.Mock(return_value=artifact.stat()),
        )
    before = factory.signature()
    artifact.write_bytes(b"other artifact")
    after = factory.signature()
    assert before != after


def test_artifact_paths_tracks_linux_pillow_library_changes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = tests.helpers.factories.peri_scribe.presentation.preview_grid
    package = tmp_path / "PIL" / "__init__.py"
    package.parent.mkdir()
    package.write_text("")
    artifact = tmp_path / "pillow.libs" / "libpillow-native.so.1"
    artifact.parent.mkdir()
    artifact.write_bytes(b"first native library")
    monkeypatch.setattr(
        peri_scribe.presentation.preview_geometry.PIL,
        "__file__",
        str(package),
    )
    paths = factory.artifact_paths()
    assert artifact in paths
    monkeypatch.setattr(factory, "ARTIFACTS", paths)
    before = factory.signature()
    artifact.write_bytes(b"other native library")
    assert factory.signature() != before


def test_history_grid_normalizes_renderer_identity_across_private_source_copies(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = tests.helpers.factories.peri_scribe.presentation.preview_grid
    renderer = pathlib.Path(peri_scribe.presentation.preview_geometry.__file__)
    copied = tmp_path / "src/peri_scribe/presentation/preview_geometry.py"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(renderer.read_bytes())
    identity = factory.signature()
    monkeypatch.setattr(
        factory,
        "ARTIFACTS",
        tuple(copied if path == renderer else path for path in factory.ARTIFACTS),
    )
    assert factory.signature() == identity
