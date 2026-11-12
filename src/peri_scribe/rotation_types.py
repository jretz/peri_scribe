"""Validate stored log rotation receipts.

[Log retention](../../docs/algorithms/log-retention.md) describes the receipt protocol.
"""

import typing

import pydantic


class RotationReceipt(pydantic.BaseModel):
    """Record checksums showing when rotation allows the plain log to be removed."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    version: typing.Literal[1] = 1
    source_checksum: str
    archive_checksum: str | None
    target_checksum: str
