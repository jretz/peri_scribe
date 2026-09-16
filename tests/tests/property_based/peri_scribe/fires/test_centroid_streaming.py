"""Tests for peri_scribe.fires.centroid_streaming."""

from __future__ import annotations

import io

import hypothesis
import hypothesis.strategies

import peri_scribe.fires.centroid_streaming


@hypothesis.given(
    chunks=hypothesis.strategies.lists(
        hypothesis.strategies.binary(max_size=50),
        max_size=20,
    ),
    sizes=hypothesis.strategies.lists(
        hypothesis.strategies.integers(-1, 100),
        max_size=20,
    ),
)
def test_byte_stream_read_matches_bytes_io(
    chunks: list[bytes],
    sizes: list[int],
) -> None:
    stream = peri_scribe.fires.centroid_streaming.ByteStream(chunks)
    reference = io.BytesIO(b"".join(chunks))
    for size in sizes:
        assert stream.read(size) == reference.read(size)
    assert stream.read() == reference.read()
