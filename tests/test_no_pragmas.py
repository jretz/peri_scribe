"""Verify every tool-disabling comment matches an approved exception."""

import tests.pragma_helpers


def test_no_pragma_comments() -> None:
    match_lines = tests.pragma_helpers.pragma_matches().splitlines()

    remaining_exceptions = list(tests.pragma_helpers.PRAGMA_COMMENT_EXCEPTIONS)
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
