import pathlib

import tests.formal.helpers.component_identity


def test_source_components_have_canonical_distinct_internal_identities() -> None:
    assert tests.formal.helpers.component_identity.check_grouping()


def test_scoring_namespaces_match_injective_reserved_prefix_encoding() -> None:
    assert tests.formal.helpers.component_identity.check_storage_keys()


def test_stored_anonymous_components_survive_publication_and_identity_corrections(
    tmp_path: pathlib.Path,
) -> None:
    assert tests.formal.helpers.component_identity.check_publications(tmp_path)


def test_report_and_checkpoint_tags_match_component_alias_priority() -> None:
    assert tests.formal.helpers.component_identity.check_tagged_keys()
