"""Tour updates preserve explicit visibility and playback durations."""

import pytest

import kml_io.tour
import tests.helpers.factories.kml_io.geometry
import tests.helpers.peri_scribe.kml.parsing
from measurement_units import units


def test_visibility_change_reveals_rings_through_index() -> None:
    assert kml_io.tour.visibility_change(["a", "b", "c"], 1) == (
        '<Placemark targetId="a"><visibility>1</visibility></Placemark>'
        '<Placemark targetId="b"><visibility>1</visibility></Placemark>'
        '<Placemark targetId="c"><visibility>0</visibility></Placemark>'
    )


@pytest.mark.parametrize("visible", [True, False])
def test_reveal_tour_preserves_name_targets_and_unit_aware_durations(
    *,
    visible: bool,
) -> None:
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    kml_io.tour.reveal_tour(
        writer,
        "Survey & changes",
        ["first", "second"],
        [500 * units.milliseconds, 0.05 * units.minutes],
        visible=visible,
    )
    document = tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer)
    tour = tests.helpers.peri_scribe.kml.parsing.tour_named(
        document,
        "Survey & changes",
    )
    assert tests.helpers.peri_scribe.kml.parsing.visibility(tour) == (
        None if visible else 0
    )
    updates = tests.helpers.peri_scribe.kml.parsing.tour_primitives(
        tour,
        tests.helpers.peri_scribe.kml.parsing.gx_tag("AnimatedUpdate"),
    )
    assert [
        tests.helpers.peri_scribe.kml.parsing.update_visibility_by_target(update)
        for update in updates
    ] == [{"first": 1, "second": 0}, {"first": 1, "second": 1}]
    waits = tests.helpers.peri_scribe.kml.parsing.tour_primitives(
        tour,
        tests.helpers.peri_scribe.kml.parsing.gx_tag("Wait"),
    )
    assert [
        tests.helpers.peri_scribe.kml.parsing.wait_duration(wait) for wait in waits
    ] == [
        0.5,
        3.0,
    ]


def test_reveal_tour_accepts_empty_sequence() -> None:
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    kml_io.tour.reveal_tour(writer, "Empty", (), ())
    document = tests.helpers.peri_scribe.kml.parsing.document_from_writer(writer)
    tour = tests.helpers.peri_scribe.kml.parsing.tour_named(document, "Empty")
    assert not tests.helpers.peri_scribe.kml.parsing.tour_primitives(
        tour,
        tests.helpers.peri_scribe.kml.parsing.gx_tag("AnimatedUpdate"),
    )


def test_reveal_tour_rejects_missing_wait_before_writing() -> None:
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    with pytest.raises(ValueError, match="Every tour placemark"):
        kml_io.tour.reveal_tour(writer, "Incomplete", ["first"], ())
    assert writer.text() == ""
