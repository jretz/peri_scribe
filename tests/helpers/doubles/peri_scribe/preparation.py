"""Year-aware stages expose cache lifecycle without generating publication artifacts."""

import pathlib

import peri_scribe.preparation
import spatial_data.product_cache


@peri_scribe.preparation.cached_year
def remembered_stage(
    year_directory: pathlib.Path,
    *values: bytes,
    unconditional: bool = False,
) -> tuple[pathlib.Path, bool, bytes | None]:
    """Observe the previous completed invocation while forwarding stage arguments.

    Args:
        year_directory: The owner of this stage's disposable state.
        values: The newly prepared payload fragments.
        unconditional: The caller's requested bypass policy.

    Returns:
        The unchanged year and policy arguments, together with the preceding payload.
    """
    prior = spatial_data.product_cache.get("stage", "input")
    spatial_data.product_cache.put("stage", "input", b"".join(values))
    return year_directory, unconditional, prior
