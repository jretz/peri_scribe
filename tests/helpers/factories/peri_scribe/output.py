"""Build inputs for output tests."""

from __future__ import annotations

import peri_scribe.models


def fire_scores_document(scores: list[int]) -> peri_scribe.models.FireScores:
    """Build a validated score document for distribution-plot tests.

    Args:
        scores: Score values used to build one fire entry each.

    Returns:
        A score document containing one named fire per supplied score.
    """
    return peri_scribe.models.FireScores.model_validate({
        "version": "2026-08-28",
        "fires": [
            {
                "name": f"Fire {index}",
                "score": score,
                "explanation": "No notable size, growth, threat, or "
                "official-importance signals.",
            }
            for index, score in enumerate(scores)
        ],
    })
