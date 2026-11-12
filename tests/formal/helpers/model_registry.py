"""Declare which complete TLC evidence each conformance consumer needs."""

import dataclasses
import enum
import functools
import pathlib
import tomllib


DIRECTORY = pathlib.Path(__file__).resolve().parents[1] / "tla"


class Export(enum.StrEnum):
    """Keep state inventories distinct from complete directed graphs."""

    GRAPH = "graph"
    STATES = "states"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Model:
    """Keep each configuration's expected outcome and evidence in one declaration."""

    name: str
    module: str
    config: str
    expected_invariant: str | None = None
    conformance: Export | None = None


def declarations(directory: pathlib.Path) -> tuple[Model, ...]:
    """Read the same declarations for model execution and conformance consumers.

    Args:
        directory: The registered specifications and their manifest.

    Returns:
        The model configurations in declared order.
    """
    with (directory / "models.toml").open("rb") as stream:
        document = tomllib.load(stream)
    models = []
    for item in document["models"]:
        export = item.pop("conformance", None)
        models.append(
            Model(**item, conformance=Export(export) if export is not None else None),
        )
    return tuple(models)


@functools.cache
def exports() -> dict[tuple[str, str], Export]:
    """Use the manifest for both cold conformance and current-run receipts.

    Returns:
        The declared evidence formats keyed by module and configuration.
    """
    return {
        (model.module, model.config): model.conformance
        for model in declarations(DIRECTORY)
        if model.conformance is not None
    }
