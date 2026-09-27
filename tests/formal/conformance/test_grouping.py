import peri_scribe.fires.grouping
import tests.formal.helpers.grouping
import tests.formal.helpers.oracle


def test_group_fire_record_indices_matches_proved_union_components() -> None:
    cases = tests.formal.helpers.grouping.graph_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.grouping.command(case) for case in cases],
        executable="oracleDomain",
    )
    for records, result in zip(cases, expected, strict=True):
        groups = peri_scribe.fires.grouping.group_fire_record_indices(records)
        assert tests.formal.helpers.grouping.canonical(groups, len(records)) == result


def test_group_fire_record_indices_name_and_spatial_edges_match_lean() -> None:
    cases = tests.formal.helpers.grouping.spatial_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.grouping.command(case) for case in cases],
        executable="oracleDomain",
    )
    for records, result in zip(cases, expected, strict=True):
        groups = peri_scribe.fires.grouping.group_fire_record_indices(records)
        assert tests.formal.helpers.grouping.canonical(groups, len(records)) == result
