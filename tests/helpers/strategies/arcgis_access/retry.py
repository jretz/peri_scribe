"""Generate retry examples with constrained domains."""

import json

import hypothesis.strategies


@hypothesis.strategies.composite
def rate_limit_representations(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[dict[str, object], str]:
    """Vary JSON layout and key order without changing the server's retry instruction.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        An ArcGIS error payload and its equivalent JSON text.
    """
    delays = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.integers(0, 3600),
            max_size=4,
        ),
    )
    fields: list[tuple[str, object]] = [
        ("code", 429),
        ("message", "Too many requests"),
        ("details", ["Server busy", *[f"Retry after {delay} sec" for delay in delays]]),
    ]
    payload: dict[str, object] = {
        "error": dict(draw(hypothesis.strategies.permutations(fields))),
    }
    indent = draw(
        hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.integers(0, 4),
        ),
    )
    return payload, json.dumps(payload, indent=indent)
