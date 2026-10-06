import pathlib

import pytest

import tests.formal.helpers.defect_baselines
import tests.formal.helpers.defect_checks


@pytest.mark.parametrize(
    "defect",
    tests.formal.helpers.defect_checks.DEFECTS,
    ids=lambda defect: defect.name,
)
def test_existing_conformance_rejects_isolated_production_defects(
    tmp_path: pathlib.Path,
    defect: tests.formal.helpers.defect_checks.Defect,
    formal_defect_baseline: tests.formal.helpers.defect_baselines.Baseline,
) -> None:
    tests.formal.helpers.defect_checks.check(defect, tmp_path, formal_defect_baseline)
