"""Source scalar identity shortcuts preserve the proved complete typed JSON equality."""

import tests.formal.helpers.json_evidence


def test_same_json_value_matches_proved_scalar_identity_comparison() -> None:
    assert (
        tests.formal.helpers.json_evidence.compare()
        == tests.formal.helpers.json_evidence.COMPARISON_COUNT
    )
