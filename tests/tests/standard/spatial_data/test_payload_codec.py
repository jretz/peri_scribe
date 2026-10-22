"""Exact cache framing bounds allocation and rejects ambiguous compressed streams."""

import compression.zstd
import hashlib
import struct
import typing
import unittest.mock

import pytest

import spatial_data.payload_codec
import spatial_data.payload_prediction


@pytest.mark.parametrize("predictor", list(spatial_data.payload_codec.Predictor))
@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 255, 256, 1025, 1048593])
def test_codec_preserves_every_byte_across_padding_and_block_boundaries(
    predictor: spatial_data.payload_codec.Predictor,
    size: int,
) -> None:
    value = (bytes(range(256)) * ((size + 255) // 256))[:size]
    frame = spatial_data.payload_codec.encode(value, predictor=predictor)
    assert spatial_data.payload_codec.decode(frame) == value
    assert spatial_data.payload_codec.decoded_size(frame) == size
    assert len(frame) <= len(value) + 1


def test_codec_uses_raw_fallback_for_incompressible_bytes() -> None:
    value = b"".join(
        hashlib.sha256(str(index).encode()).digest() for index in range(32)
    )
    assert spatial_data.payload_codec.encode(value) == b"\x10" + value


def test_codec_authenticates_exact_dictionary_bytes() -> None:
    dictionary = compression.zstd.train_dict(
        [f'{{"sample":{index},"repeated":"abcdef"}}'.encode() for index in range(100)],
        512,
    ).dict_content
    value = b'{"sample":1,"repeated":"abcdef"}' * 100
    frame = spatial_data.payload_codec.encode(value, dictionary=dictionary)
    assert frame[0] & spatial_data.payload_codec.DICTIONARY_FLAG
    assert spatial_data.payload_codec.decode(frame, dictionary=dictionary) == value
    for incorrect in (None, dictionary[:-1]):
        with pytest.raises(ValueError, match="dictionary"):
            spatial_data.payload_codec.decode(frame, dictionary=incorrect)


def test_codec_rejects_oversized_payload_before_compression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(spatial_data.payload_codec, "MAX_DECODED_BYTES", 2)
    with pytest.raises(ValueError, match="limit"):
        spatial_data.payload_codec.encode(b"123")
    with pytest.raises(ValueError, match="header"):
        spatial_data.payload_codec.decoded_size(b"\x10123")


@pytest.mark.parametrize(
    "frame",
    [
        b"",
        b"\xff",
        struct.pack("<BQI", 0xFF, 256, 1),
        struct.pack("<BQI", 0x11, 0, 0),
        struct.pack("<BQI", 0x11, 256, 2),
        struct.pack("<BQI", 0x11, 2**40, 1),
    ],
)
def test_codec_rejects_invalid_version_length_and_block_count(frame: bytes) -> None:
    with pytest.raises(ValueError, match="header"):
        spatial_data.payload_codec.decode(frame)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        struct.pack("<II", 255, 1) + b"x",
        struct.pack("<II", 256, 0),
        struct.pack("<II", 256, 2**25),
        struct.pack("<II", 256, 10) + b"x",
        struct.pack("<II", 256, 1) + b"x",
    ],
)
def test_codec_rejects_missing_and_invalid_compressed_blocks(body: bytes) -> None:
    with pytest.raises(ValueError, match=r"block|compressed"):
        spatial_data.payload_codec.decode(struct.pack("<BQI", 0x11, 256, 1) + body)


def test_codec_rejects_trailing_bytes_after_complete_frame() -> None:
    frame = spatial_data.payload_codec.encode(b"a" * 1000)
    with pytest.raises(ValueError, match="trailing"):
        spatial_data.payload_codec.decode(frame + b"x")


@pytest.mark.parametrize("variant", ["short", "long", "truncated", "concatenated"])
def test_codec_requires_exact_complete_single_zstd_block(variant: str) -> None:
    original = b"a" * 256
    compressed = compression.zstd.compress(original)
    if variant == "short":
        compressed = compression.zstd.compress(original[:-1])
    elif variant == "long":
        compressed = compression.zstd.compress(original + b"a")
    elif variant == "truncated":
        compressed = compressed[:-1]
    else:
        compressed += compression.zstd.compress(b"b")
    frame = struct.pack("<BQI", 0x11, 256, 1)
    frame += struct.pack("<II", 256, len(compressed)) + compressed
    with pytest.raises(ValueError, match="truncated, oversized, or has trailing"):
        spatial_data.payload_codec.decode(frame)


@pytest.mark.parametrize("operation", ["encode", "decode"])
def test_codec_wraps_zstd_failures_as_optional_cache_validation_errors(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = spatial_data.payload_codec.encode(b"a" * 1000)
    monkeypatch.setattr(
        compression.zstd,
        "compress" if operation == "encode" else "ZstdDecompressor",
        unittest.mock.Mock(side_effect=compression.zstd.ZstdError("unavailable")),
    )
    function = typing.cast(
        "typing.Callable[[bytes], bytes]",
        getattr(spatial_data.payload_codec, operation),
    )
    with pytest.raises(ValueError, match="invalid"):
        function(b"a" * 1000 if operation == "encode" else frame)


def test_predictor_empty_input_round_trip() -> None:
    assert spatial_data.payload_prediction.predict(b"") == b""
    assert spatial_data.payload_prediction.restore(b"", 0) == b""
