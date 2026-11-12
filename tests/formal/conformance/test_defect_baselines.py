import pathlib
import shutil
import sys
import typing
import unittest.mock

import pydantic
import pytest

import tests.formal.helpers.defect_baselines
import tests.formal.helpers.defect_checks
import tests.formal.helpers.fixtures.defects
import tests.formal.helpers.oracle
import tests.formal.helpers.process


def test_isolated_assertion_diagnostics_survive_relocated_pytest_bytecode(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = tests.formal.helpers.defect_baselines
    root = tests.formal.helpers.oracle.DIRECTORY.parents[1]
    original = tmp_path / "original"
    source = original / "src"
    source.mkdir(parents=True)
    (source / "relocated_subject.py").write_text("value = 1\n")
    (original / "pytest.ini").write_text("[pytest]\n")
    conformance = original / "conformance"
    conformance.mkdir()
    (conformance / "test_relocated.py").write_text(
        "import relocated_subject\n\n"
        "def test_relocated():\n"
        "    observed = relocated_subject.value\n"
        "    expected = 2\n"
        "    assert observed == expected\n",
    )
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    seeded = tests.formal.helpers.process.run(
        [
            sys.executable,
            "-c",
            (
                "import os, sys, pytest; os.environ.pop('PYTEST_ADDOPTS', None); "
                "sys.dont_write_bytecode = False; sys.path.insert(0, sys.argv[1]); "
                "raise SystemExit(pytest.main(sys.argv[2:]))"
            ),
            str(source),
            "-c",
            str(original / "pytest.ini"),
            "--disable-plugin-autoload",
            "-q",
            str(conformance / "test_relocated.py"),
        ],
        cwd=root,
        timeout=30,
    )
    assert seeded.returncode == 1, seeded.stdout + seeded.stderr
    assert list((conformance / "__pycache__").glob("test_relocated.*-pytest-*.pyc"))
    relocated = tmp_path / "relocated"
    shutil.copytree(original, relocated)
    shutil.rmtree(original)
    monkeypatch.setattr(tests.formal.helpers.oracle, "DIRECTORY", relocated)
    report = relocated / "result.xml"
    target = namespace.Target(
        module="relocated_subject",
        test="test_relocated.py::test_relocated",
    )
    rejected = tests.formal.helpers.process.run(
        [
            *namespace.command(relocated / "src", relocated, (target,)),
            f"--junitxml={report}",
        ],
        cwd=root,
        timeout=30,
    )
    assert rejected.returncode == 1, rejected.stdout + rejected.stderr
    namespace.checked_rejection(report, target.test, "assert observed == expected")
    assert str(original) not in rejected.stdout


@pytest.mark.parametrize(
    "cases",
    [
        "",
        '<testcase classname="conformance.test_example" name="test_different"/>',
        '<testcase classname="conformance.other.test_example" name="test_target"/>',
        (
            '<testcase classname="conformance.test_example" name="test_target">'
            '<skipped message="unavailable"/></testcase>'
        ),
        (
            '<testcase classname="conformance.test_example" name="test_target">'
            '<error message="collection failed"/></testcase>'
        ),
        (
            '<testcase classname="conformance.test_example" name="test_target">'
            '<failure message="assertion failed"/></testcase>'
        ),
        '<testcase classname="conformance.test_example" name="test_target"/>' * 2,
    ],
)
def test_checked_report_rejects_missing_substituted_or_unsuccessful_baselines(
    tmp_path: pathlib.Path,
    cases: str,
) -> None:
    report = tmp_path / "results.xml"
    report.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
    with pytest.raises(AssertionError):
        tests.formal.helpers.defect_baselines.checked_report(
            report,
            ("test_example.py::test_target",),
        )


def test_checked_report_retains_exact_parameterized_target_identity(
    tmp_path: pathlib.Path,
) -> None:
    report = tmp_path / "results.xml"
    report.write_text(
        '<testsuites><testsuite><testcase classname="conformance.test_example" '
        'name="test_target[chart-axis]"/></testsuite></testsuites>',
    )
    tests.formal.helpers.defect_baselines.checked_report(
        report,
        ("test_example.py::test_target[chart-axis]",),
    )


@pytest.mark.parametrize(
    "cases",
    [
        "",
        '<testcase classname="conformance.test_example" name="test_target"/>',
        (
            '<testcase classname="conformance.test_example" name="test_target">'
            "<skipped/></testcase>"
        ),
        (
            '<testcase classname="conformance.test_example" name="test_target">'
            "<error>intended rejection</error></testcase>"
        ),
        (
            '<testcase classname="conformance.test_example" name="test_target">'
            "<failure>intended rejection</failure><error>teardown failed</error>"
            "</testcase>"
        ),
        (
            '<testcase classname="conformance.test_example" name="test_target">'
            "<failure>unrelated assertion</failure></testcase>"
        ),
        (
            '<testcase classname="conformance.test_example" name="test_other">'
            "<failure>intended rejection</failure></testcase>"
        ),
        (
            '<testcase classname="conformance.test_example" name="test_target">'
            "<failure>intended rejection</failure></testcase>"
        )
        * 2,
    ],
)
def test_checked_rejection_requires_exact_semantic_failure_without_fixture_errors(
    tmp_path: pathlib.Path,
    cases: str,
) -> None:
    report = tmp_path / "results.xml"
    report.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
    with pytest.raises(AssertionError):
        tests.formal.helpers.defect_baselines.checked_rejection(
            report,
            "test_example.py::test_target",
            "intended rejection",
        )


def test_checked_rejection_retains_parameter_identity_and_decoded_diagnostic(
    tmp_path: pathlib.Path,
) -> None:
    report = tmp_path / "results.xml"
    report.write_text(
        '<testsuites><testsuite><testcase classname="conformance.test_example" '
        'name="test_target[chart-axis]"><failure>assert value &lt; limit</failure>'
        "</testcase></testsuite></testsuites>",
    )
    tests.formal.helpers.defect_baselines.checked_rejection(
        report,
        "test_example.py::test_target[chart-axis]",
        "assert value < limit",
    )


def test_check_rejects_changed_source_before_launching_a_mutant(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defect = tests.formal.helpers.defect_checks.DEFECTS[0]
    process = unittest.mock.create_autospec(tests.formal.helpers.process.run)
    monkeypatch.setattr(tests.formal.helpers.process, "run", process)
    baseline = tests.formal.helpers.defect_baselines.Baseline(
        files={},
        tests=(defect.test,),
    )

    with pytest.raises(AssertionError):
        tests.formal.helpers.defect_checks.check(defect, tmp_path, baseline)

    process.assert_not_called()


def test_remove_targets_preserves_nearby_tests_and_parameter_variants() -> None:
    prefix = "conformance/test_example.py::test_target"
    target = f"{prefix}[example]"
    kept = [
        typing.cast("pytest.Item", unittest.mock.Mock(spec=pytest.Item, nodeid=node))
        for node in (f"{prefix}[example-other]", f"{prefix}_related[example]", prefix)
    ]
    moved = typing.cast(
        "pytest.Item",
        unittest.mock.Mock(spec=pytest.Item, nodeid=target),
    )
    items = [kept[0], moved, *kept[1:]]
    assert tests.formal.helpers.fixtures.defects.remove_targets(items, {target}) == [
        moved,
    ]
    assert items == kept
    with pytest.raises(pytest.UsageError, match="each exact pristine target once"):
        tests.formal.helpers.fixtures.defects.remove_targets(items, {target})


def test_require_pristine_targets_requires_exact_targets_and_current_source(
    tmp_path: pathlib.Path,
) -> None:
    namespace = tests.formal.helpers.fixtures.defects
    with pytest.raises(FileNotFoundError):
        namespace.require_pristine_targets(tmp_path)
    registered = tests.formal.helpers.defect_checks.DEFECTS
    targets = tuple(dict.fromkeys(defect.test for defect in registered))
    source = tests.formal.helpers.oracle.DIRECTORY.parents[1] / "src"
    files = tests.formal.helpers.defect_baselines.fingerprints(source)
    receipt = tmp_path / f"{namespace.baseline_name(registered)}.json"
    adapter = pydantic.TypeAdapter(tests.formal.helpers.defect_baselines.Baseline)
    receipt.write_bytes(
        adapter.dump_json(
            tests.formal.helpers.defect_baselines.Baseline(
                files=files,
                tests=targets[1:],
            ),
        ),
    )
    with pytest.raises(ValueError, match="removed conformance targets"):
        namespace.require_pristine_targets(tmp_path)
    receipt.write_bytes(
        adapter.dump_json(
            tests.formal.helpers.defect_baselines.Baseline(files={}, tests=targets),
        ),
    )
    with pytest.raises(ValueError, match="current production source"):
        namespace.require_pristine_targets(tmp_path)
    receipt.write_bytes(
        adapter.dump_json(
            tests.formal.helpers.defect_baselines.Baseline(files=files, tests=targets),
        ),
    )
    assert namespace.require_pristine_targets(tmp_path) == len(targets)
