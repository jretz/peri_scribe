"""Keep tool-disabling comments limited to the declared exceptions.

Lint and type-checking directives can silently remove checks, so this test checks every
comment beginning with a known directive, such as noqa, ruff: ignore, or type: ignore.
Ripgrep searches both src and tests through mise, using the project's recorded version.

Every matching comment must have exactly one declared exception, and every exception
must match one comment. Two identical lines therefore need two exceptions. Checking both
directions catches new suppressions as well as exceptions that are no longer needed.
"""

from __future__ import annotations

import dataclasses
import pathlib
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]

import pytest


@dataclasses.dataclass(frozen=True, kw_only=True)
class PragmaCommentException:
    """A pragma comment occurrence that is deliberately allowed in one file."""

    file_path: str
    code: str
    comment: str

    def matches(self, match_line: str) -> bool:
        """Return whether one ripgrep match line equals this exception.

        Args:
            match_line: One ripgrep match line in path:line:content form.

        Returns:
            Whether the line's file, code, and comment equal this exception.
        """
        file_path, _, remainder = match_line.partition(":")
        _, _, content = remainder.partition(":")
        code, _, comment = content.partition("#")
        return (
            self.file_path == file_path
            and self.code == code.strip()
            and self.comment == comment.strip()
        )


# Coding agents should never add a new exception to this list.
PRAGMA_COMMENT_EXCEPTIONS: tuple[PragmaCommentException, ...] = (
    PragmaCommentException(
        file_path="tests/helpers/code_analysis/pragmas.py",
        code="import subprocess",
        comment="ruff: ignore[suspicious-subprocess-import]",
    ),
    PragmaCommentException(
        file_path="tests/conftest.py",
        code="@pytest.fixture(autouse=True)",
        comment="ruff: ignore[pytest-fixture-autouse]",
    ),
)


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[3]


# The comment directives that suppress tool diagnostics. Each must be the first token of
# a comment so prose that merely mentions a directive is not flagged.
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
    # Mise puts the project's recorded ripgrep version on the test environment's path.
    rg_path = shutil.which("rg")
    if rg_path is None:
        pytest.fail("rg is required to run the pragma check")
    result = subprocess.run(
        [
            rg_path,
            "--no-config",
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
