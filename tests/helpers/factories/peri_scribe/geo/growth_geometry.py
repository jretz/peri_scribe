"""Load bounded operands that exposed erroneous growth-union hole filling."""

import pathlib

import shapely


FIXTURE_DIRECTORY = (
    pathlib.Path(__file__).resolve().parents[3]
    / "fixtures/peri_scribe/geo/growth_geometry"
)


def hole_union_operands(
    case: str = "0432",
) -> tuple[shapely.Geometry, shapely.Geometry]:
    """Return original 0432, minimized 0432, or Hagen hole-filling operands.

    Args:
        case: The saved case name: ``0432``, ``minimal``, or ``hagen``.

    Returns:
        The valid polygonal or mixed operands that exposed a union failure.
    """
    if case == "hagen":
        left, right = (
            shapely.from_wkb((FIXTURE_DIRECTORY / f"{case}-{side}.wkb").read_bytes())
            for side in ("left", "right")
        )
    else:
        left, right = (
            shapely.from_wkt((FIXTURE_DIRECTORY / f"{case}-{side}.wkt").read_text())
            for side in ("left", "right")
        )
    return left, right
