"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import peri_scribe.fires.identity
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.fires.scores


def test_identity_key_prefers_identifier() -> None:
    assert peri_scribe.fires.identity.identity_key("Bug", "2026-x") == "2026-x"


def test_identity_key_falls_back_to_name() -> None:
    assert peri_scribe.fires.identity.identity_key("Bug", None) == "name:Bug"


def test_group_keys_aligns_with_rows() -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.perimeter_frame(
        [
            {"fire_name": "Bug", "fire_identifier": "2026-a"},
            {"fire_name": "Bug", "fire_identifier": "2026-a"},
            {"fire_name": "Other", "fire_identifier": None},
        ],
        [
            tests.helpers.factories.geometry.square(1.0),
            tests.helpers.factories.geometry.square(2.0),
            tests.helpers.factories.geometry.square(3.0),
        ],
    )
    assert peri_scribe.fires.identity.group_keys(frame).tolist() == [
        "2026-a",
        "2026-a",
        "name:Other",
    ]


def test_identity_key_separates_component_namespace_from_external_identifiers() -> None:
    component = peri_scribe.fires.identity.identity_key("Canyon", None, "a")
    external = peri_scribe.fires.identity.identity_key("Canyon", "component:a")
    assert component != external


def test_identity_key_separates_legacy_name_namespace_from_external_identifiers() -> (
    None
):
    named = peri_scribe.fires.identity.identity_key("Canyon", None)
    external = peri_scribe.fires.identity.identity_key("Canyon", "name:Canyon")
    assert named != external
