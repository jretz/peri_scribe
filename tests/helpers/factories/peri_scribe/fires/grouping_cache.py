"""Build complete source identities for incremental grouping tests."""

from __future__ import annotations

import peri_scribe.geo.fingerprints
import peri_scribe.geo.package
import peri_scribe.models


def row_keys(records: list[peri_scribe.models.FireRecord]) -> tuple[str, ...]:
    """Use the production canonical row contract while varying grouping evidence.

    Args:
        records: Complete parsed source records in occurrence order.

    Returns:
        Complete exact evidence keys for these synthetic source occurrences.
    """
    return tuple(
        peri_scribe.geo.fingerprints.row_evidence_fingerprint(
            peri_scribe.geo.package.FireRowRecord(
                record=record,
                object_id=None,
                source_name="Grouping test",
                attributes={},
            ),
        )
        for record in records
    )
