import tests.formal.helpers.identity_output


def test_area_positions_and_history_row_index_match_distinct_identity_contracts() -> (
    None
):
    tests.formal.helpers.identity_output.check_keyed_selection()


def test_prepare_fire_data_matches_grouped_history_and_output_contracts() -> None:
    for case in tests.formal.helpers.identity_output.cases():
        tests.formal.helpers.identity_output.check(case)
