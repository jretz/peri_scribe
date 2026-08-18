"""Output operations for peri_scribe."""

import json
import pathlib
from typing import TYPE_CHECKING

import structlog


if TYPE_CHECKING:
    import peri_scribe.models


def write_geopackage(
    path: pathlib.Path,
    layers: list[peri_scribe.models.LayerData],
) -> None:
    logger = structlog.get_logger()
    if path.exists():
        path.unlink()
        logger.info("Replaced existing", path=path.name)
    mode = "w"
    for layer_data in layers:
        layer_data.dataframe.to_file(
            path,
            driver="GPKG",
            layer=layer_data.name,
            mode=mode,
        )
        logger.info(
            "Wrote layer",
            layer=layer_data.name,
            features=len(layer_data.dataframe),
        )
        mode = "a"


def write_fire_index(
    path: pathlib.Path,
    document: peri_scribe.models.FireIndex,
) -> None:
    """Write *document* to *path* as pretty-printed JSON.

    Args:
        path: The JSON file to write.
        document: The validated fire index to serialize.
    """
    logger = structlog.get_logger()
    with path.open("w", encoding="utf-8") as file:
        json.dump(document.model_dump(), file, indent=4)
    logger.info("Wrote fire index", path=path.name, fires=len(document.fires))


def configure_logging(log_level: str) -> None:
    """Configure structlog with the minimum log level."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%S%z", utc=False),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )
