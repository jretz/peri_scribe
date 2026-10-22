import pathlib
import tempfile

import tests.formal.helpers.cache_compaction
import tests.formal.helpers.corpus


def test_compact_preserves_checked_execution_paths(tmp_path: pathlib.Path) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "ParsedCacheCompaction",
        "ParsedCacheCompaction",
        tmp_path / "tlc",
    )
    checked = tests.formal.helpers.cache_compaction.contract(graph)
    originals = {checked.values[state][0] for state in graph.initial}
    assert len(originals) == tests.formal.helpers.cache_compaction.CONFIGURATION_COUNT
    for original in originals:
        for stop in (
            *range(tests.formal.helpers.cache_compaction.CLOSURE_BOUNDARY + 1),
            None,
        ):
            with tempfile.TemporaryDirectory(dir=tmp_path) as name:
                tests.formal.helpers.cache_compaction.replay(
                    checked,
                    pathlib.Path(name),
                    original,
                    stop,
                )
        with tempfile.TemporaryDirectory(dir=tmp_path) as name:
            tests.formal.helpers.cache_compaction.replay(
                checked,
                pathlib.Path(name),
                original,
                None,
                corrupt=True,
            )
