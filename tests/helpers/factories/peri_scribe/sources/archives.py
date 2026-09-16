"""Build inputs for archives tests."""

from __future__ import annotations

import html


def section_heading(text: str, level: int, *, wrapped: bool) -> str:
    """Represent headings in plain HTML and GitHub's Markdown wrapper.

    Args:
        text: The heading's visible label.
        level: Its HTML heading level.
        wrapped: Whether the heading has GitHub's wrapper element.

    Returns:
        The section heading's markup.
    """
    heading = f"<h{level}><span>{html.escape(text)}</span></h{level}>"
    return f'<div class="markdown-heading">{heading}</div>' if wrapped else heading
