import functools
import pathlib

import pytest

import tests.formal.helpers.cache_chart_bundles
import tests.formal.helpers.cache_context
import tests.formal.helpers.cache_dependencies


@pytest.mark.parametrize(
    ("product", "change"),
    [
        (product, change)
        for product in (
            "chart",
            "history",
            "description",
            "buffer",
            "boundary",
            "rings",
        )
        for change in (
            *getattr(tests.formal.helpers.cache_dependencies, product.upper()).consumed,
            *getattr(tests.formal.helpers.cache_dependencies, product.upper()).wrappers,
        )
        if change != "bundle"
    ],
)
def test_product_keys_preserve_declared_dependencies_and_exact_fresh_results(
    tmp_path: pathlib.Path,
    product: str,
    change: str,
) -> None:
    render = getattr(tests.formal.helpers.cache_dependencies, product)
    contract = getattr(tests.formal.helpers.cache_dependencies, product.upper())
    tests.formal.helpers.cache_dependencies.check_transition(
        tmp_path,
        contract,
        change,
        functools.partial(render, ""),
        functools.partial(render, change),
    )


def test_plot_image_bundles_keeps_cached_images_with_current_fire_owners(
    tmp_path: pathlib.Path,
) -> None:
    tests.formal.helpers.cache_chart_bundles.compare(tmp_path)


@pytest.mark.parametrize(
    "change",
    tests.formal.helpers.cache_dependencies.BUILDINGS.consumed,
)
def test_building_counts_keys_include_exact_dataset_and_query_dependencies(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    tests.formal.helpers.cache_dependencies.building_transition(tmp_path, change)


@pytest.mark.parametrize("change", tests.formal.helpers.cache_context.CONTRACT.consumed)
def test_runtime_fingerprint_completes_product_dependencies(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    tests.formal.helpers.cache_context.compare(tmp_path, change)
