"""Check compatibility boundaries for cached native dependencies."""

import pathlib

import pytest

import tests.helpers.mise


@pytest.mark.asyncio
async def test_mise_environment_shared_cache_isolates_checkouts_with_same_name(
    tmp_path: pathlib.Path,
) -> None:
    shared_cache = tmp_path / "shared-uv"
    first = await tests.helpers.mise.mise_environment(
        tmp_path / "first" / "project",
        cache_root=shared_cache,
    )
    second = await tests.helpers.mise.mise_environment(
        tmp_path / "second" / "project",
        cache_root=shared_cache,
    )

    assert first["GEOS_LIBRARY_PATH"] != second["GEOS_LIBRARY_PATH"]
    assert first["UV_CACHE_DIR"] != second["UV_CACHE_DIR"]


@pytest.mark.asyncio
async def test_mise_environment_shared_cache_reuses_same_checkout(
    tmp_path: pathlib.Path,
) -> None:
    checkout = tmp_path / "project"
    shared_cache = tmp_path / "shared-uv"
    first = await tests.helpers.mise.mise_environment(checkout, cache_root=shared_cache)
    second = await tests.helpers.mise.mise_environment(
        checkout,
        cache_root=shared_cache,
    )

    assert first["UV_CACHE_DIR"] == second["UV_CACHE_DIR"]
    assert pathlib.Path(first["UV_CACHE_DIR"]).is_relative_to(shared_cache)


@pytest.mark.asyncio
async def test_mise_environment_shared_cache_isolates_geos_versions(
    tmp_path: pathlib.Path,
) -> None:
    checkout = tmp_path / "project"
    shared_cache = tmp_path / "shared-uv"
    first = await tests.helpers.mise.mise_environment(checkout, cache_root=shared_cache)
    second = await tests.helpers.mise.mise_environment(
        checkout,
        cache_root=shared_cache,
        geos_version=f"{first['GEOS_VERSION']}-different",
    )

    assert first["UV_CACHE_DIR"] != second["UV_CACHE_DIR"]


@pytest.mark.asyncio
async def test_mise_environment_local_cache_stays_in_checkout(
    tmp_path: pathlib.Path,
) -> None:
    checkout = tmp_path / "project"
    environment = await tests.helpers.mise.mise_environment(checkout)

    assert pathlib.Path(environment["UV_CACHE_DIR"]).is_relative_to(
        checkout / ".cache" / "uv",
    )
