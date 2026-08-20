"""Tests for peri_scribe.kml_template."""

from __future__ import annotations

import pathlib
import typing

import fastkml
import pyproj
import pytest

import peri_scribe.kml_template


@pytest.fixture
def document() -> fastkml.Document:
    """Return the parsed document of the generated KML template.

    Returns:
        The template's Document.
    """
    kml = fastkml.KML.from_string(peri_scribe.kml_template.template_kml())
    return typing.cast("fastkml.Document", kml.features[0])


def folder_named(
    container: fastkml.Document | fastkml.Folder,
    name: str,
) -> fastkml.Folder:
    for feature in container.features:
        if isinstance(feature, fastkml.Folder) and feature.name == name:
            return feature
    pytest.fail(f"Folder {name!r} not found")


def placemark_named(folder: fastkml.Folder, name: str) -> fastkml.Placemark:
    for feature in folder.features:
        if isinstance(feature, fastkml.Placemark) and feature.name == name:
            return feature
    pytest.fail(f"Placemark {name!r} not found")


def style_with_id(document: fastkml.Document, style_id: str) -> fastkml.Style:
    for candidate in document.styles:
        if isinstance(candidate, fastkml.Style) and candidate.id == style_id:
            return candidate
    pytest.fail(f"Style {style_id!r} not found")


def placemark_style_url(placemark: fastkml.Placemark) -> str:
    style_url = placemark.style_url
    if style_url is None or style_url.url is None:
        pytest.fail("Placemark has no styleUrl")
    return style_url.url


def poly_style_of(style: fastkml.Style) -> fastkml.PolyStyle:
    for candidate in style.styles:
        if isinstance(candidate, fastkml.PolyStyle):
            return candidate
    pytest.fail("Style has no PolyStyle")


def line_style_of(style: fastkml.Style) -> fastkml.LineStyle:
    for candidate in style.styles:
        if isinstance(candidate, fastkml.LineStyle):
            return candidate
    pytest.fail("Style has no LineStyle")


def icon_style_of(style: fastkml.Style) -> fastkml.IconStyle:
    for candidate in style.styles:
        if isinstance(candidate, fastkml.IconStyle):
            return candidate
    pytest.fail("Style has no IconStyle")


def interior_coordinates(placemark: fastkml.Placemark) -> list[tuple[float, float]]:
    """Return the coordinates of *placemark*'s polygon hole, or [] when it has none.

    Args:
        placemark: The placemark to inspect.

    Returns:
        The hole ring's (longitude, latitude) coordinates, or an empty list when the
        placemark's polygon is solid.
    """
    geometry = placemark.kml_geometry
    if not isinstance(geometry, fastkml.Polygon):
        pytest.fail("Placemark has no polygon geometry")
    inner_boundaries = geometry.inner_boundaries
    if not inner_boundaries:
        return []
    ring = inner_boundaries[0].geometry
    if ring is None:
        pytest.fail("Inner boundary has no ring geometry")
    return typing.cast("list[tuple[float, float]]", list(ring.coords))


def exterior_coordinates(placemark: fastkml.Placemark) -> list[tuple[float, float]]:
    """Return the outer ring coordinates of *placemark*'s polygon.

    Args:
        placemark: The placemark to inspect.

    Returns:
        The outer ring's (longitude, latitude) coordinates.
    """
    geometry = placemark.kml_geometry
    if not isinstance(geometry, fastkml.Polygon):
        pytest.fail("Placemark has no polygon geometry")
    outer_boundary = geometry.outer_boundary
    if outer_boundary is None:
        pytest.fail("Placemark has no outer boundary")
    ring = outer_boundary.geometry
    if ring is None:
        pytest.fail("Outer boundary has no ring geometry")
    return typing.cast("list[tuple[float, float]]", list(ring.coords))


def point_coordinates(placemark: fastkml.Placemark) -> tuple[float, float]:
    """Return the (longitude, latitude) of *placemark*'s point geometry.

    Args:
        placemark: The placemark to inspect.

    Returns:
        The point's (longitude, latitude).
    """
    geometry = placemark.kml_geometry
    if not isinstance(geometry, fastkml.Point):
        pytest.fail("Placemark has no point geometry")
    point = geometry.geometry
    if point is None:
        pytest.fail("Point has no coordinates")
    return point.x, point.y


def bounding_box_center(coordinates: list[tuple[float, float]]) -> tuple[float, float]:
    """Return the center of the bounding box of *coordinates*.

    The center is unaffected by the closing duplicate of a closed ring, and for a
    square it is exactly the square's center.

    Args:
        coordinates: The coordinates to bound.

    Returns:
        The bounding box center (longitude, latitude).
    """
    longitudes = [longitude for longitude, _latitude in coordinates]
    latitudes = [latitude for _longitude, latitude in coordinates]
    return (
        (min(longitudes) + max(longitudes)) / 2,
        (min(latitudes) + max(latitudes)) / 2,
    )


def assert_two_kilometers_due_west(longitude: float, latitude: float) -> None:
    """Assert that the point is 2 km due west of the template's point location.

    Args:
        longitude: The longitude of the point to check.
        latitude: The latitude of the point to check.
    """
    geodesic = pyproj.Geod(ellps="WGS84")
    azimuth, _back_azimuth, distance = geodesic.inv(
        peri_scribe.kml_template.POINT_CENTER.longitude,
        peri_scribe.kml_template.POINT_CENTER.latitude,
        longitude,
        latitude,
    )
    assert distance == pytest.approx(2_000)
    assert azimuth == pytest.approx(-90.0)


def test_template_path_returns_data_templates_file() -> None:
    assert peri_scribe.kml_template.template_path() == pathlib.Path(
        "data",
        "templates",
        "PeriScribe Template.kml",
    )


def test_kml_color_converts_hex_and_opacity_to_aabbggrr() -> None:
    assert peri_scribe.kml_template.kml_color("#FF0000", 0) == "000000ff"
    assert peri_scribe.kml_template.kml_color("#FFFFFF", 0) == "00ffffff"
    assert peri_scribe.kml_template.kml_color("#FF0000", 50) == "7f0000ff"
    assert peri_scribe.kml_template.kml_color("#FF0000", 100) == "ff0000ff"
    assert peri_scribe.kml_template.kml_color("#FF2A00", 50) == "7f002aff"
    assert peri_scribe.kml_template.kml_color("#FFFF00", 100) == "ff00ffff"
    assert peri_scribe.kml_template.kml_color("#FFFFFF", 100) == "ffffffff"


def test_square_coordinates_returns_closed_centered_ring() -> None:
    coordinates = peri_scribe.kml_template.square_coordinates(
        800,
        peri_scribe.kml_template.POINT_CENTER,
    )
    assert coordinates[0] == coordinates[-1]

    corners = coordinates[:-1]
    assert len(set(corners)) == len(corners)

    longitudes = [longitude for longitude, _latitude in corners]
    latitudes = [latitude for _longitude, latitude in corners]
    assert sum(longitudes) / len(corners) == pytest.approx(
        peri_scribe.kml_template.POINT_CENTER.longitude,
    )
    assert sum(latitudes) / len(corners) == pytest.approx(
        peri_scribe.kml_template.POINT_CENTER.latitude,
    )


def test_center_west_of_returns_point_two_kilometers_due_west() -> None:
    west = peri_scribe.kml_template.center_west_of(
        peri_scribe.kml_template.POINT_CENTER,
        2_000,
    )
    assert_two_kilometers_due_west(west.longitude, west.latitude)


def test_reversed_ring_reverses_direction_and_stays_closed() -> None:
    ring = [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
        (0.0, 0.0),
    ]
    assert peri_scribe.kml_template.reversed_ring(ring) == [
        (0.0, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
        (1.0, 0.0),
        (0.0, 0.0),
    ]


def test_template_kml_defines_point_style(document: fastkml.Document) -> None:
    point_style = style_with_id(document, "point-icon")
    assert icon_style_of(point_style).icon_href == (
        peri_scribe.kml_template.POINT_ICON_URL
    )


def test_template_kml_has_two_top_level_folders(document: fastkml.Document) -> None:
    names = [
        feature.name
        for feature in document.features
        if isinstance(feature, fastkml.Folder)
    ]
    assert names == [
        peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
        "Perimeter Progression Maps",
    ]


def test_template_kml_filled_perimeter_folder(document: fastkml.Document) -> None:
    filled = folder_named(
        document,
        peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
    )

    point = placemark_named(filled, "Point Location")
    assert placemark_style_url(point) == "#point-icon"

    fill = placemark_named(filled, "Latest Area")
    assert placemark_style_url(fill) == "#perimeter-fill"
    assert interior_coordinates(fill) == []
    fill_style = style_with_id(document, "perimeter-fill")
    fill_poly_style = poly_style_of(fill_style)
    assert fill_poly_style.color == "7f0000ff"
    assert fill_poly_style.fill is True
    assert fill_poly_style.outline is False

    outline_placemarks = [
        feature
        for feature in filled.features
        if isinstance(feature, fastkml.Placemark)
        and feature.name not in {"Point Location", "Latest Area"}
    ]
    expected_colors = {
        "Latest Outline": "ff0000ff",
        "Penultimate Outline": "ff00ffff",
        "Antepenultimate Outline": "ffffffff",
    }
    assert len(outline_placemarks) == len(expected_colors)
    for name, color in expected_colors.items():
        outline_placemark = placemark_named(filled, name)
        style_id = placemark_style_url(outline_placemark).removeprefix("#")
        outline_style = style_with_id(document, style_id)
        line_style = line_style_of(outline_style)
        assert line_style.color == color
        assert line_style.width == pytest.approx(1.5)
        outline_poly_style = poly_style_of(outline_style)
        assert outline_poly_style.color == "00ffffff"
        assert outline_poly_style.fill is True
        assert outline_poly_style.outline is True


def test_template_kml_filled_perimeter_orders_placemarks(
    document: fastkml.Document,
) -> None:
    filled = folder_named(
        document,
        peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    placemark_names = [
        feature.name
        for feature in filled.features
        if isinstance(feature, fastkml.Placemark)
    ]
    assert placemark_names == [
        "Point Location",
        "Latest Area",
        "Latest Outline",
        "Penultimate Outline",
        "Antepenultimate Outline",
    ]


def test_template_kml_filled_perimeter_geometry_is_two_kilometers_due_west(
    document: fastkml.Document,
) -> None:
    filled = folder_named(
        document,
        peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
    )

    point = placemark_named(filled, "Point Location")
    point_longitude, point_latitude = point_coordinates(point)
    assert_two_kilometers_due_west(point_longitude, point_latitude)

    fill = placemark_named(filled, "Latest Area")
    polygons = [
        fill,
        *[
            placemark_named(filled, template.name)
            for template in peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES
        ],
    ]
    for polygon in polygons:
        polygon_longitude, polygon_latitude = bounding_box_center(
            exterior_coordinates(polygon),
        )
        assert polygon_longitude == pytest.approx(point_longitude)
        assert polygon_latitude == pytest.approx(point_latitude)


def test_template_kml_progression_map_folder(document: fastkml.Document) -> None:
    progression = folder_named(document, "Perimeter Progression Maps")

    point = placemark_named(progression, "Point Location")
    assert placemark_style_url(point) == "#point-icon"

    fill_placemarks = [
        feature
        for feature in progression.features
        if isinstance(feature, fastkml.Placemark) and feature.name != "Point Location"
    ]
    expected_colors = {
        "Latest Day": "7f002aff",
        "2 Days Before That": "7f0073ff",
        "4 Days Before That": "7f00aaff",
        "8 Days Before That": "7f3359b3",
        "16 Days Before That": "7f3b476e",
        "32 Days Before That": "7f4a4a4a",
        "64 Days Before That": "7f8a827a",
        "128+ Days Before That": "7fbdb7b0",
    }
    assert len(fill_placemarks) == len(expected_colors)
    for name, color in expected_colors.items():
        fill_placemark = placemark_named(progression, name)
        style_id = placemark_style_url(fill_placemark).removeprefix("#")
        fill_style = style_with_id(document, style_id)
        fill_poly_style = poly_style_of(fill_style)
        assert fill_poly_style.color == color
        assert fill_poly_style.fill is True
        assert fill_poly_style.outline is False


def test_template_kml_progression_map_geometry_stays_at_point(
    document: fastkml.Document,
) -> None:
    progression = folder_named(document, "Perimeter Progression Maps")
    point = placemark_named(progression, "Point Location")
    longitude, latitude = point_coordinates(point)
    assert longitude == pytest.approx(
        peri_scribe.kml_template.POINT_CENTER.longitude,
    )
    assert latitude == pytest.approx(
        peri_scribe.kml_template.POINT_CENTER.latitude,
    )


def test_template_kml_progression_map_polygons_exclude_smaller_squares(
    document: fastkml.Document,
) -> None:
    progression = folder_named(document, "Perimeter Progression Maps")
    templates = peri_scribe.kml_template.PROGRESSION_FILL_TEMPLATES
    for index, template in enumerate(templates[:-1]):
        next_template = templates[index + 1]
        placemark = placemark_named(progression, template.name)
        expected_hole = set(
            peri_scribe.kml_template.square_coordinates(
                next_template.side_length_in_meters,
                peri_scribe.kml_template.POINT_CENTER,
            ),
        )
        assert set(interior_coordinates(placemark)) == expected_hole
    smallest_placemark = placemark_named(progression, templates[-1].name)
    assert interior_coordinates(smallest_placemark) == []


class RecordingFile:
    """In-memory file stand-in that keeps its contents after being closed."""

    def __init__(self) -> None:
        self.content = ""

    def write(self, text: str) -> int:
        self.content += text
        return len(text)

    def __enter__(self) -> typing.Self:
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc_value: object,
        _traceback: object,
    ) -> None:
        return None


def test_write_template_writes_template_kml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/templates/PeriScribe Template.kml")
    files: list[RecordingFile] = []
    made_directories: list[pathlib.Path] = []

    def fake_open(
        _self: pathlib.Path,
        mode: str,
        encoding: str,
    ) -> RecordingFile:
        assert mode == "w"
        assert encoding == "utf-8"
        file = RecordingFile()
        files.append(file)
        return file

    def fake_mkdir(
        _self: pathlib.Path,
        *,
        parents: bool,
        exist_ok: bool,
    ) -> None:
        assert parents is True
        assert exist_ok is True
        made_directories.append(_self)

    monkeypatch.setattr(pathlib.Path, "open", fake_open)
    monkeypatch.setattr(pathlib.Path, "mkdir", fake_mkdir)

    peri_scribe.kml_template.write_template(path)

    assert made_directories == [pathlib.Path("/templates")]
    assert files[0].content == peri_scribe.kml_template.template_kml()


def test_create_template_writes_to_template_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    output_path = tmp_path / "PeriScribe Template.kml"
    monkeypatch.setattr(
        peri_scribe.kml_template,
        "template_path",
        lambda: output_path,
    )
    writes: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.kml_template,
        "write_template",
        writes.append,
    )
    output = peri_scribe.kml_template.create_template()
    assert output == output_path
    assert writes == [output_path]


def test_create_template_refuses_to_overwrite_existing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    output_path = tmp_path / "PeriScribe Template.kml"
    output_path.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(
        peri_scribe.kml_template,
        "template_path",
        lambda: output_path,
    )
    writes: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.kml_template,
        "write_template",
        writes.append,
    )
    output = peri_scribe.kml_template.create_template()
    assert output is None
    assert writes == []
    assert output_path.read_text(encoding="utf-8") == "existing"


def test_create_template_force_overwrites_existing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    output_path = tmp_path / "PeriScribe Template.kml"
    output_path.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(
        peri_scribe.kml_template,
        "template_path",
        lambda: output_path,
    )
    writes: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.kml_template,
        "write_template",
        writes.append,
    )
    output = peri_scribe.kml_template.create_template(force=True)
    assert output == output_path
    assert writes == [output_path]
