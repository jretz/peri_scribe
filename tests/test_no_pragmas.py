"""Guarantee no tool-disabling comments survive in the source.

The conventions forbid disabling lint or type-checking rules on individual lines, so no
comment that starts a known directive (noqa, ruff: ignore, type: ignore, and so on) may
appear anywhere in src or tests. Ripgrep, run through mise so the project's pinned
version is used, searches both trees. Each pragma comment found must match exactly one
declared exception, and each exception must match one comment, so two identical lines in
a file need the same exception declared twice. The prohibition is enforced by the test
suite rather than by review alone.
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
        file_path="tests/test_no_pragmas.py",
        code="import subprocess",
        comment="ruff: ignore[suspicious-subprocess-import]",
    ),
    PragmaCommentException(
        file_path="tests/conftest.py",
        code="@pytest.fixture(autouse=True)",
        comment="ruff: ignore[pytest-fixture-autouse]",
    ),
)


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent.parent


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
    match_lines = pragma_matches().splitlines()

    remaining_exceptions = list(PRAGMA_COMMENT_EXCEPTIONS)
    unexpected_pragma_lines: list[str] = []
    for match_line in match_lines:
        matching_exception = next(
            (
                exception
                for exception in remaining_exceptions
                if exception.matches(match_line)
            ),
            None,
        )
        if matching_exception is None:
            unexpected_pragma_lines.append(match_line)
        else:
            remaining_exceptions.remove(matching_exception)

    assert not unexpected_pragma_lines, "Pragmas are not allowed:\n" + "\n".join(
        unexpected_pragma_lines,
    )
    assert not remaining_exceptions, "Unused pragma exceptions:\n" + "\n".join(
        f"{exception.file_path}: {exception.code}  # {exception.comment}"
        for exception in remaining_exceptions
    )
