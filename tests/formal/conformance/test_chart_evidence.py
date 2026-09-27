"""Complete source streams and styled SVG paths follow the checked evidence model."""

import tests.formal.helpers.chart_evidence


def test_contained_perimeter_points_matches_independent_history_reference() -> None:
    assert len(tests.formal.helpers.chart_evidence.histories()) == (
        tests.formal.helpers.chart_evidence.HISTORY_CASE_COUNT
    )
    tests.formal.helpers.chart_evidence.check_independent_histories()


def test_contained_perimeter_points_preserves_stored_history_composition() -> None:
    tests.formal.helpers.chart_evidence.check_stored_history_composition()


def test_line_segments_preserves_all_source_edges_and_legend_styles() -> None:
    assert len(tests.formal.helpers.chart_evidence.point_histories()) == (
        tests.formal.helpers.chart_evidence.SEGMENT_CASE_COUNT
    )
    tests.formal.helpers.chart_evidence.check_segment_histories(rendered=False)


def test_draw_plot_preserves_proved_edges_and_styles_in_saved_svg() -> None:
    tests.formal.helpers.chart_evidence.check_segment_histories(rendered=True)
