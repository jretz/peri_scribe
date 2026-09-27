"""Invalid durable intent must survive rejection without acknowledgment or append."""

import json
import pathlib

import pydantic
import pytest

import peri_scribe.fire_update_records
import peri_scribe.fire_updates
import tests.helpers.factories.peri_scribe.durable_updates


@pytest.mark.parametrize(
    "field",
    ["perimeters", "aliases", "names", "sources", "lineage", "owners"],
)
def test_state_rejects_invalid_identity_keys(field: str) -> None:
    value: object = (
        tests.helpers.factories.peri_scribe.durable_updates.IDENTITY
        if field in {"aliases", "owners"}
        else []
    )
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_updates.State.model_validate({field: {"bad": value}})


@pytest.mark.parametrize("field", ["aliases", "lineage", "owners"])
@pytest.mark.parametrize("target", ["bad", '["id","fire"]', '["id", 1]'])
def test_state_rejects_invalid_identity_targets(field: str, target: str) -> None:
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_updates.State.model_validate({
            field: {
                tests.helpers.factories.peri_scribe.durable_updates.IDENTITY: (
                    [target] if field == "lineage" else target
                ),
            },
        })


def test_state_preserves_cycles_chains_and_shared_lineage() -> None:
    first, second, third = (json.dumps(("local", value)) for value in ("a", "b", "c"))
    state = peri_scribe.fire_updates.State(
        aliases={first: second, second: third},
        owners={first: second, second: first, third: second},
        lineage={first: frozenset({first, second}), second: frozenset({first, second})},
    )

    assert peri_scribe.fire_updates.State.model_validate_json(
        state.model_dump_json(),
    ) == (state)


@pytest.mark.parametrize(
    "override",
    [
        {"state": {"version": 2}},
        {"state": {"unknown": True}},
        {"timestamp": "2026-09-26T12:00:00"},
        {"batch_id": ""},
        {"records": [{"name": "Incomplete"}]},
    ],
)
def test_pending_updates_validates_every_durable_field(
    override: dict[str, object],
) -> None:
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_updates.PendingUpdates.model_validate(
            tests.helpers.factories.peri_scribe.durable_updates.pending() | override,
        )


@pytest.mark.parametrize("content", [b"{", {"records": [{}]}])
def test_recover_updates_rejects_invalid_pending_without_mutation(
    tmp_path: pathlib.Path,
    content: object,
) -> None:
    raw = (
        {**tests.helpers.factories.peri_scribe.durable_updates.pending(), **content}
        if isinstance(content, dict)
        else content
    )
    tests.helpers.factories.peri_scribe.durable_updates.write(
        peri_scribe.fire_updates.pending_path(tmp_path),
        raw,
    )
    before = tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path)

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_updates.recover_updates(tmp_path)

    assert (
        tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path) == before
    )


def test_write_updates_rejects_invalid_checkpoint_before_recovering_pending(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.durable_updates.write(
        peri_scribe.fire_updates.state_path(tmp_path),
        b"{",
    )
    tests.helpers.factories.peri_scribe.durable_updates.write(
        peri_scribe.fire_updates.pending_path(tmp_path),
        tests.helpers.factories.peri_scribe.durable_updates.pending(),
    )
    prepared = peri_scribe.fire_updates.PreparedUpdates(
        records=(tests.helpers.factories.peri_scribe.durable_updates.record(),),
        state=tests.helpers.factories.peri_scribe.durable_updates.state(2),
    )
    before = tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path)

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    assert (
        tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path) == before
    )


def test_write_updates_validates_records_before_equal_state_shortcut(
    tmp_path: pathlib.Path,
) -> None:
    state = tests.helpers.factories.peri_scribe.durable_updates.state()
    tests.helpers.factories.peri_scribe.durable_updates.write(
        peri_scribe.fire_updates.state_path(tmp_path),
        state.model_dump(mode="json"),
    )
    prepared = peri_scribe.fire_updates.PreparedUpdates(records=({},), state=state)
    before = tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path)

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    assert (
        tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path) == before
    )


def test_write_updates_validates_entire_batch_before_recovering_pending(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.durable_updates.write(
        peri_scribe.fire_updates.pending_path(tmp_path),
        tests.helpers.factories.peri_scribe.durable_updates.pending(),
    )
    prepared = peri_scribe.fire_updates.PreparedUpdates(
        records=(tests.helpers.factories.peri_scribe.durable_updates.record(), {}),
        state=tests.helpers.factories.peri_scribe.durable_updates.state(2),
    )
    before = tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path)

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    assert (
        tests.helpers.factories.peri_scribe.durable_updates.contents(tmp_path) == before
    )


def test_write_updates_revalidates_mutated_nested_payloads(
    tmp_path: pathlib.Path,
) -> None:
    record = tests.helpers.factories.peri_scribe.durable_updates.record()
    record["mapped_area"] = peri_scribe.fire_update_records.Acreage.model_construct(
        value=-1,
    )
    prepared = peri_scribe.fire_updates.PreparedUpdates(
        records=(record,),
        state=tests.helpers.factories.peri_scribe.durable_updates.state(),
    )

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    assert not list(tmp_path.iterdir())


def test_write_updates_revalidates_mutated_state(tmp_path: pathlib.Path) -> None:
    state = tests.helpers.factories.peri_scribe.durable_updates.state()
    state.owners[tests.helpers.factories.peri_scribe.durable_updates.IDENTITY] = "bad"
    prepared = peri_scribe.fire_updates.PreparedUpdates(records=(), state=state)

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    assert not list(tmp_path.iterdir())
