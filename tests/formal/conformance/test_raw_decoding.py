"""Compare raw feed parsers and typed field fallback with checked Lean semantics."""

import peri_scribe.geo.parsing
import peri_scribe.perimeters.history_attributes
import peri_scribe.sources.changes
import tests.formal.helpers.raw_decoding


NUMERIC_SCALARS = 56
NUMERIC_SELECTIONS = 1897
TEXT_SELECTIONS = 1783
TIMESTAMP_SCALARS = 92
TIMESTAMP_SELECTIONS = 2005
EFFECTIVE_TIME_SELECTIONS = 288


def test_numeric_value_and_float_attribute_match_lean() -> None:
    candidates = tests.formal.helpers.raw_decoding.numeric_candidates()
    assert (
        tests.formal.helpers.raw_decoding.check_scalars(
            candidates,
            peri_scribe.geo.parsing.numeric_value,
            operation="fields",
        )
        == NUMERIC_SCALARS
    )
    assert (
        tests.formal.helpers.raw_decoding.check_fields(
            candidates,
            peri_scribe.perimeters.history_attributes.float_attribute,
            operation="fields",
        )
        == NUMERIC_SELECTIONS
    )


def test_text_attribute_matches_lean() -> None:
    assert (
        tests.formal.helpers.raw_decoding.check_fields(
            tests.formal.helpers.raw_decoding.text_candidates(),
            peri_scribe.perimeters.history_attributes.text_attribute,
            operation="fields",
        )
        == TEXT_SELECTIONS
    )


def test_observation_time_from_and_modified_datetime_from_match_lean() -> None:
    assert (
        tests.formal.helpers.raw_decoding.check_scalars(
            tests.formal.helpers.raw_decoding.time_candidates(epoch_milliseconds=False),
            peri_scribe.geo.parsing.observation_time_from,
            operation="times",
        )
        == TIMESTAMP_SCALARS
    )
    candidates = tests.formal.helpers.raw_decoding.time_candidates(
        epoch_milliseconds=True,
    )
    assert (
        tests.formal.helpers.raw_decoding.check_scalars(
            candidates,
            peri_scribe.sources.changes.modified_datetime_from,
            operation="times",
        )
        == TIMESTAMP_SCALARS
    )
    assert (
        tests.formal.helpers.raw_decoding.check_fields(
            candidates,
            peri_scribe.perimeters.history_attributes.datetime_attribute,
            operation="times",
        )
        == TIMESTAMP_SELECTIONS
    )


def test_effective_time_uses_first_valid_row_timestamp_before_snapshot() -> None:
    assert tests.formal.helpers.raw_decoding.check_effective_times() == (
        EFFECTIVE_TIME_SELECTIONS
    )
