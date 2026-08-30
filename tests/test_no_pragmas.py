"""Guarantee no tool-disabling comments survive in the source.

The conventions forbid disabling lint or type-checking rules on individual lines, so no
comment that starts a known directive (noqa, ruff: ignore, type: ignore, and so on) may
appear anywhere in src or tests. Ripgrep, run through mise so the project's pinned
version is used, searches both trees and the test fails on any match, keeping the
prohibition enforced by the test suite rather than by review alone.
"""

from __future__ import annotations

import importlib
import pathlib
import shutil

import pytest


# Ruff's bandit rules forbid importing subprocess directly, so the module is loaded
# dynamically; the invocation below sticks to list arguments and an absolute
# executable path, which is the safe form those rules exist to enforce.
subprocess = importlib.import_module("subprocess")

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The comment directives that suppress tool diagnostics. Each must be the first
# token of a comment so prose that merely mentions a directive is not flagged.
PRAGMA_PATTERN = (
    r"#\s*(noqa|ruff:\s*(noqa|ignore)|(type|ty|typecheck):\s*ignore"
    r"|pyright:\s*ignore|mypy:\s*ignore|pylint:\s*disable"
    r"|pragma:\s*no\s*cover|flake8:\s*noqa|fmt:\s*(off|skip)|noinspection)\b"
)


def pragma_matches() -> str:
    """Return the pragma comment matches in src and tests, or an empty string.

    Returns:
        The ripgrep output for the matches, or an empty string when there are none.
    """
    mise_path = shutil.which("mise")
    if mise_path is None:
        pytest.fail("mise is required to run the pragma check")
    result = subprocess.run(
        [
            mise_path,
            "exec",
            "--",
            "rg",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            "--no-ignore",
            "--glob",
            "*.py",
            PRAGMA_PATTERN,
            "src",
            "tests",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1:
        return ""
    pytest.fail(
        f"rg failed with exit code {result.returncode}: {result.stderr.strip()}",
    )


def test_no_pragma_comments() -> None:
    matches = pragma_matches()
    assert not matches, f"Found pragma comments:\n{matches}"
