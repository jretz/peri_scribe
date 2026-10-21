import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.normalized_cache


def test_fetch_snapshot_batch_matches_checked_dictionary_publication(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "NormalizedCache",
        "NormalizedCache",
        tmp_path / "tlc",
    )
    for phase in ("published", "aborted"):
        configurations = tests.formal.helpers.normalized_cache.configurations(
            states,
            phase,
        )
        assert (
            len(configurations)
            == tests.formal.helpers.normalized_cache.CONFIGURATION_COUNT
        )
        for original, target in configurations:
            tests.formal.helpers.normalized_cache.replay(
                original,
                target,
                commit=phase == "published",
            )
