import peri_scribe.models


def test_fire_complex_links_fires_circularly() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    fire_complex = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({fire}),
    )
    assert fire.complex is fire_complex
    assert fire_complex.fires == frozenset({fire})
    assert next(iter(fire_complex.fires)).complex is fire_complex


def test_fire_complex_does_not_link_when_it_has_no_fires() -> None:
    fire_complex = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset(),
    )
    assert fire_complex.fires == frozenset()


def test_fire_equality_ignores_complex() -> None:
    left_fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    right_fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({left_fire}),
    )
    peri_scribe.models.FireComplex(
        name="HAY CREEK COMPLEX",
        identifier="851ddf21-4ead-4835-b54b-b3cf7bd6ac21",
        fires=frozenset({right_fire}),
    )
    assert left_fire == right_fire


def test_fire_hash_ignores_complex() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    hash_before = hash(fire)
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({fire}),
    )
    assert hash(fire) == hash_before
    assert fire == peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )


def test_fire_complex_equality() -> None:
    left = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({
            peri_scribe.models.Fire(
                name="Crosswhite",
                status=peri_scribe.models.FireStatus.ACTIVE,
            ),
        }),
    )
    right = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({
            peri_scribe.models.Fire(
                name="Crosswhite",
                status=peri_scribe.models.FireStatus.ACTIVE,
            ),
        }),
    )
    assert left == right


def test_fire_complex_repr_does_not_recurse() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    fire_complex = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({fire}),
    )
    assert "ROWE CREEK COMPLEX" in repr(fire_complex)
    assert "Crosswhite" in repr(fire_complex)
    assert "complex" not in repr(fire)


def test_is_globally_unique_identifier() -> None:
    assert peri_scribe.models.is_globally_unique_identifier(
        "286b7f1d-8945-4a5d-9d81-5235c18af1fe",
    )
    assert not peri_scribe.models.is_globally_unique_identifier("2026-nvccd-030683")
    assert not peri_scribe.models.is_globally_unique_identifier("not-a-guid")


def test_is_unique_fire_identifier() -> None:
    assert peri_scribe.models.is_unique_fire_identifier("2026-nvccd-030683")
    assert not peri_scribe.models.is_unique_fire_identifier(
        "286b7f1d-8945-4a5d-9d81-5235c18af1fe",
    )
    assert not peri_scribe.models.is_unique_fire_identifier("z-1")


def test_canonical_fire_identifier_prefers_unique_then_guid_then_other() -> None:
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    unique = "2026-nvccd-030683"
    assert peri_scribe.models.canonical_fire_identifier({unique, guid}) == unique
    assert peri_scribe.models.canonical_fire_identifier({guid}) == guid
    assert peri_scribe.models.canonical_fire_identifier({"z-1"}) == "z-1"
    assert peri_scribe.models.canonical_fire_identifier(set()) is None


def test_normalize_fire_name_treats_separators_as_spaces() -> None:
    assert peri_scribe.models.normalize_fire_name("  Park   FIRE ") == "park fire"
    assert peri_scribe.models.normalize_fire_name("SANTA-ROSA") == "santa rosa"
    assert peri_scribe.models.normalize_fire_name("3-1") == "3 1"


def test_fire_aliases_default_to_empty() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    assert fire.aliases == frozenset()
