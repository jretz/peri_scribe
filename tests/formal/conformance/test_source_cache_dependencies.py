import pathlib

import pytest

import tests.formal.helpers.source_cache_dependencies


@pytest.mark.parametrize(
    "change",
    [
        *tests.formal.helpers.source_cache_dependencies.CONTRACT.consumed,
        *tests.formal.helpers.source_cache_dependencies.CONTRACT.wrappers,
    ],
)
def test_classifications_for_prepared_sources_preserve_complete_key_dependencies(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    tests.formal.helpers.source_cache_dependencies.compare(tmp_path, change)
