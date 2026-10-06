import pathlib
import unittest.mock

import pytest

import tests.formal.helpers.defect_baselines
import tests.formal.helpers.defect_checks
import tests.formal.helpers.process


@pytest.mark.parametrize(
    "cases",
    [
        "",
        '<testcase classname="conformance.test_example" name="test_different"/>',
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
