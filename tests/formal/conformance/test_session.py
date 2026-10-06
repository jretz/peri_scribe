import json
import pathlib

import pytest

import tests.formal.helpers.session


def test_scope_shares_only_while_its_owner_is_alive(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tests.formal.helpers.session.scope(tmp_path):
        assert tests.formal.helpers.session.directory() == tmp_path
        marker = (tmp_path / "session.json").read_text()
    (tmp_path / "session.json").write_text(marker)
    monkeypatch.setenv(tests.formal.helpers.session.VARIABLE, str(tmp_path))
    with pytest.raises(RuntimeError, match="owner has exited"):
        tests.formal.helpers.session.directory()


def test_directory_rejects_changed_specifications_within_one_session(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_directory = tmp_path / "specifications"
    (model_directory / "tla").mkdir(parents=True)
    (model_directory / "tla" / "models.toml").write_text("models = []")
    model = model_directory / "tla" / "Example.tla"
    model.write_text("Original model")
    monkeypatch.setattr(
        tests.formal.helpers.session,
        "FORMAL_DIRECTORY",
        model_directory,
    )
    with tests.formal.helpers.session.scope(tmp_path / "corpus"):
        assert tests.formal.helpers.session.directory() == tmp_path / "corpus"
        model.write_text("Different model")
        with pytest.raises(RuntimeError, match="different specifications"):
            tests.formal.helpers.session.directory()


def test_temporary_removes_evidence_and_starts_each_run_fresh() -> None:
    with tests.formal.helpers.session.temporary() as first:
        (first / "evidence.json").write_text(json.dumps({"checked": True}))
    with tests.formal.helpers.session.temporary() as second:
        assert first != second
        assert not (second / "evidence.json").exists()
        assert not first.exists()
    assert not second.exists()
