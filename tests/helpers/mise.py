"""Evaluate project environment settings without tools or host configuration."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
import tomllib


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]


async def mise_environment(
    checkout: pathlib.Path,
    *,
    cache_root: pathlib.Path | None = None,
    geos_version: str | None = None,
) -> dict[str, str]:
    """Resolve the real environment templates in an isolated checkout.

    Args:
        checkout: Temporary project location for resolving native library paths.
        cache_root: Optional shared uv cache root used by CI.
        geos_version: Optional GEOS version for checking cache compatibility.

    Returns:
        Environment variables resolved by mise for the temporary checkout.
    """
    configuration = tomllib.loads(
        (REPOSITORY_ROOT / ".mise/config.toml").read_text(),
    )["env"]
    del configuration["_"]
    if geos_version is not None:
        configuration["GEOS_VERSION"] = geos_version
    configuration_directory = checkout / ".mise"
    configuration_directory.mkdir(parents=True, exist_ok=True)
    (configuration_directory / "config.toml").write_text(
        "[env]\n"
        + "\n".join(
            f"{name} = {json.dumps(value)}" for name, value in configuration.items()
        )
        + "\n",
    )
    isolated_root = checkout.parent / "mise-state"
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "MISE_CEILING_PATHS": str(checkout.parent),
        "MISE_TRUSTED_CONFIG_PATHS": str(checkout),
        **{
            f"MISE_{name}_DIR": str(isolated_root / name.lower())
            for name in ("CONFIG", "CACHE", "STATE", "DATA", "SYSTEM_CONFIG")
        },
    }
    if cache_root is not None:
        environment["PERI_SCRIBE_UV_CACHE_ROOT"] = str(cache_root)
    mise_path = shutil.which("mise")
    assert mise_path is not None, "mise is required to verify environment configuration"
    process = await asyncio.create_subprocess_exec(
        mise_path,
        "env",
        "--json",
        cwd=checkout,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, errors = await process.communicate()
    assert process.returncode == 0, errors.decode()
    return json.loads(output)
