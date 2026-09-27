import pathlib

import pytest

import tests.formal.helpers.defect_checks


@pytest.mark.parametrize(
    "defect",
    tests.formal.helpers.defect_checks.DEFECTS,
    ids=lambda defect: defect.name,
)
def test_existing_conformance_rejects_isolated_production_defects(
    tmp_path: pathlib.Path,
    defect: tests.formal.helpers.defect_checks.Defect,
) -> None:
    tests.formal.helpers.defect_checks.check(defect, tmp_path)
