"""Shared row shading keeps terminal lists readable across themes and layouts."""

import collections.abc
import functools
import typing

import rich.segment
import rich.style
import textual.color
import textual.filter

import peri_scribe.monitor.screenshots


@functools.lru_cache(maxsize=256)
def tint_background(
    background: textual.color.Color,
    tint: textual.color.Color,
) -> textual.color.Color:
    """Preserve stripe brightness while adding a subtle status hue.

    Args:
        background: The row's background after alternating shading.
        tint: The status accent whose hue should be recognizable.

    Returns:
        A tinted background with the same brightness, within RGB rounding precision.
    """
    brightness_change = (tint.brightness - background.brightness) * 255
    changes = tuple(
        target - channel - brightness_change
        for channel, target in zip(background.rgb, tint.rgb, strict=True)
    )
    amount = 0.12
    for channel, change in zip(background.rgb, changes, strict=True):
        if change:
            limit = (255 - channel) / change if change > 0 else -channel / change
            amount = min(amount, limit)
    return textual.color.Color(
        *(
            round(channel + amount * change)
            for channel, change in zip(
                background.rgb,
                changes,
                strict=True,
            )
        ),
        a=background.a,
    )


class AlternatingRows(textual.filter.LineFilter):
    """Row metadata keeps stripes aligned through scrolling, wrapping, and folding."""

    @typing.override
    def apply(
        self,
        segments: list[rich.segment.Segment],
        background: textual.color.Color,
    ) -> list[rich.segment.Segment]:
        """Shade ordinary row backgrounds while retaining interaction highlights.

        Args:
            segments: Rendered cells with Textual's table, tree, or option metadata.
            background: The widget's background after theme and focus adjustments.

        Returns:
            Cells with alternating backgrounds and unchanged text and mouse targets.
        """
        stripe = background.blend(background.get_contrast_text(), 0.05)
        result = []
        for segment in segments:
            style = segment.style
            if style is not None:
                row = style.meta.get(
                    "row",
                    style.meta.get("line", style.meta.get("option", -1)),
                )
                if row >= 0 and style.bgcolor == background.rich_color:
                    row_background = stripe if row % 2 else background
                    if tint := style.meta.get("row_tint"):
                        row_background = tint_background(
                            row_background,
                            textual.color.Color.parse(tint),
                        )
                    result.append(
                        rich.segment.Segment(
                            segment.text,
                            style + rich.style.Style(bgcolor=row_background.rich_color),
                            segment.control,
                        ),
                    )
                    continue
            result.append(segment)
        return result


class StripedApp(peri_scribe.monitor.screenshots.SnapshotApp):
    """Apply the same row shading to all terminal views and built-in controls."""

    ROW_STRIPES = AlternatingRows()

    @typing.override
    def get_line_filters(self) -> collections.abc.Sequence[textual.filter.LineFilter]:
        """Keep status hues and alternating rows consistent across the application.

        Returns:
            Shared row shading followed by the terminal's accessibility filters.
        """
        return [self.ROW_STRIPES, *super().get_line_filters()]
