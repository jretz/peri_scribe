"""Tests for peri_scribe.operations."""

import pathlib
import re
import typing

import pytest

import peri_scribe.exceptions
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.operations


ACTIVE = peri_scribe.models.FireStatus.ACTIVE
INACTIVE = peri_scribe.models.FireStatus.INACTIVE


def test_list_fires_prefers_most_common_mixed_case_spelling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fire_names(
        _path: pathlib.Path,
    ) -> typing.Generator[peri_scribe.models.Fire]:
        yield peri_scribe.models.Fire(name="PARK FIRE", status=ACTIVE)
        yield peri_scribe.models.Fire(name="PARK FIRE", status=ACTIVE)
        yield peri_scribe.models.Fire(name="PARK FIRE", status=ACTIVE)
        yield peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_names",
        fake_fire_names,
    )
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)]


def test_list_fires_uses_most_common_spelling_when_none_is_mixed_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fire_names(
        _path: pathlib.Path,
    ) -> typing.Generator[peri_scribe.models.Fire]:
        yield peri_scribe.models.Fire(name="PARK FIRE", status=INACTIVE)
        yield peri_scribe.models.Fire(name="park fire", status=INACTIVE)
        yield peri_scribe.models.Fire(name="park fire", status=INACTIVE)

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_names",
        fake_fire_names,
    )
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [peri_scribe.models.Fire(name="park fire", status=INACTIVE)]


def test_list_fires_breaks_mixed_case_ties_by_first_spelling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fire_names(
        _path: pathlib.Path,
    ) -> typing.Generator[peri_scribe.models.Fire]:
        yield peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)
        yield peri_scribe.models.Fire(name="PARK Fire", status=ACTIVE)

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_names",
        fake_fire_names,
    )
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)]


def test_is_mixed_case() -> None:
    assert peri_scribe.operations.is_mixed_case("Park Fire")
    assert not peri_scribe.operations.is_mixed_case("PARK FIRE")
    assert not peri_scribe.operations.is_mixed_case("park fire")
    assert not peri_scribe.operations.is_mixed_case("3-1")


def test_list_fires_marks_fire_active_when_any_record_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fire_names(
        _path: pathlib.Path,
    ) -> typing.Generator[peri_scribe.models.Fire]:
        yield peri_scribe.models.Fire(name="ALTA", status=INACTIVE)
        yield peri_scribe.models.Fire(name="Alta", status=ACTIVE)

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_names",
        fake_fire_names,
    )
    fires = peri_scribe.operations.list_fires((pathlib.Path("one.gpkg"),))
    assert fires == [peri_scribe.models.Fire(name="Alta", status=ACTIVE)]


def test_list_fires_merges_names_across_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fire_names(
        path: pathlib.Path,
    ) -> typing.Generator[peri_scribe.models.Fire]:
        if path.name == "one.gpkg":
            yield peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)
            yield peri_scribe.models.Fire(name="ALTA", status=INACTIVE)
        else:
            yield peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)
            yield peri_scribe.models.Fire(name="Creek Fire", status=ACTIVE)

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_names",
        fake_fire_names,
    )
    fires = peri_scribe.operations.list_fires(
        (pathlib.Path("one.gpkg"), pathlib.Path("two.gpkg")),
    )
    assert fires == [
        peri_scribe.models.Fire(name="Park Fire", status=ACTIVE),
        peri_scribe.models.Fire(name="ALTA", status=INACTIVE),
        peri_scribe.models.Fire(name="Creek Fire", status=ACTIVE),
    ]


def test_list_fires_propagates_unknown_layer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fire_names(_path: pathlib.Path) -> typing.Never:
        layer_name = "Mystery_Layer_0"
        raise peri_scribe.exceptions.UnknownLayerError(
            layer_name,
            pathlib.Path("fires.gpkg"),
        )

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_names",
        fake_fire_names,
    )
    with pytest.raises(
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        peri_scribe.operations.list_fires((pathlib.Path("fires.gpkg"),))


def test_list_fires_raises_system_exit_for_unreadable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fire_names(_path: pathlib.Path) -> typing.Never:
        message = "no such file"
        raise FileNotFoundError(message)

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_names",
        fake_fire_names,
    )
    with pytest.raises(
        SystemExit,
        match=re.escape("Failed to read fires.gpkg: no such file"),
    ):
        peri_scribe.operations.list_fires((pathlib.Path("fires.gpkg"),))
