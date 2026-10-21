"""Real documents preserve source text and reserve structure for generated markup."""

import pathlib

import tests.formal.helpers.output_text


def test_source_text_encodings_match_checked_preservation_contract() -> None:
    tests.formal.helpers.output_text.check_encodings()


def test_normalized_matches_checked_definition_for_every_python_codepoint() -> None:
    tests.formal.helpers.output_text.check_normalization_codepoints()


def test_shared_balloon_variants_preserve_checked_text_and_row_structure() -> None:
    tests.formal.helpers.output_text.check_balloon_variants()


def test_saved_markdown_and_kmz_preserve_source_fields_and_structure(
    tmp_path: pathlib.Path,
) -> None:
    tests.formal.helpers.output_text.check_artifacts(tmp_path)
