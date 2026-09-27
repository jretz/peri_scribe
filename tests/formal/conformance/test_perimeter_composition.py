"""The complete perimeter pipeline agrees with its proved provenance composition."""

import peri_scribe.perimeters.history
import tests.formal.helpers.oracle
import tests.formal.helpers.perimeter_composition


def test_reconcile_preserves_order_attributes_and_justifies_rejected_lineage() -> None:
    cases = tests.formal.helpers.perimeter_composition.histories()
    commands = [
        " ".join([operation, str(preferred), *(entry.command() for entry in case)])
        for case in cases
        for preferred in (0, 1)
        for operation in ("reconciled", "compose")
    ]
    expected = iter(
        tests.formal.helpers.oracle.evaluate(commands, executable="oraclePerimeters"),
    )
    for case in cases:
        for preferred in (0, 1):
            entries = [entry.production() for entry in case]
            before = tests.formal.helpers.perimeter_composition.before_size_filter(
                entries,
                preferred,
            )
            actual = peri_scribe.perimeters.history.reconcile(
                entries,
                tests.formal.helpers.perimeter_composition.classification(preferred),
            )
            assert tests.formal.helpers.perimeter_composition.retained(before) == next(
                expected,
            ), (case, preferred)
            assert tests.formal.helpers.perimeter_composition.retained(actual) == next(
                expected,
            ), (case, preferred)
