"""Store exact disposable payloads in bounded, versioned zstd frames.

Design: [Exact compressed payloads](../../docs/algorithms/compressed-payloads.md).
"""

import compression.zstd
import enum
import hashlib
import struct

import spatial_data.payload_prediction


BLOCK_BYTES = 1024 * 1024
MAX_BLOCKS = 256
MAX_DECODED_BYTES = BLOCK_BYTES * MAX_BLOCKS
MAX_ENCODED_BLOCK_BYTES = BLOCK_BYTES + 65536
MINIMUM_COMPRESSION_BYTES = 256
RAW_TAG = 0x10
ZSTD_TAG = 0x11
PREDICTED_TAG = 0x12
DICTIONARY_FLAG = 0x20
HEADER = struct.Struct("<BQI")
BLOCK_HEADER = struct.Struct("<II")
DICTIONARY_DIGEST_BYTES = 32


class Predictor(enum.Enum):
    """Select an exact byte transform independently of the payload's logical type."""

    NONE = ZSTD_TAG
    XOR16_SHUFFLE = PREDICTED_TAG


def encode(
    value: bytes,
    *,
    dictionary: bytes | None = None,
    predictor: Predictor = Predictor.NONE,
) -> bytes:
    """Compress independent bounded blocks, retaining raw bytes when they are smaller.

    Args:
        value: The complete logical payload whose checksum remains authoritative.
        dictionary: Immutable trained zstd bytes owned by the storage generation.
        predictor: Optional reversible coordinate-byte prediction and lane permutation.

    Returns:
        A complete version-one frame, including a tag even for an uncompressed value.

    Raises:
        ValueError: If the payload exceeds the optional cache limit or encoding fails.
    """
    if len(value) > MAX_DECODED_BYTES:
        message = "Payload exceeds the bounded cache codec limit"
        raise ValueError(message)
    if len(value) < MINIMUM_COMPRESSION_BYTES:
        return bytes([RAW_TAG]) + value
    try:
        frame = compress_frame(value, dictionary, predictor)
    except compression.zstd.ZstdError as error:
        message = "Payload dictionary or zstd encoding is invalid"
        raise ValueError(message) from error
    return frame if len(frame) < len(value) + 1 else bytes([RAW_TAG]) + value


def compress_frame(
    value: bytes,
    dictionary: bytes | None,
    predictor: Predictor,
) -> bytes:
    """Encode independent blocks under one exact dictionary identity.

    Args:
        value: Original bytes within the caller's declared size bound.
        dictionary: Optional immutable dictionary owned by the cache transaction.
        predictor: The reversible byte transform selected for this payload.

    Returns:
        Complete compressed framing, which the caller compares with raw storage.
    """
    prepared = compression.zstd.ZstdDict(dictionary) if dictionary is not None else None
    tag = predictor.value | (DICTIONARY_FLAG if dictionary is not None else 0)
    frame = bytearray(
        HEADER.pack(tag, len(value), (len(value) + BLOCK_BYTES - 1) // BLOCK_BYTES),
    )
    if dictionary is not None:
        frame.extend(hashlib.sha256(dictionary).digest())
    for position in range(0, len(value), BLOCK_BYTES):
        block = value[position : position + BLOCK_BYTES]
        predicted = (
            spatial_data.payload_prediction.predict(block)
            if predictor is Predictor.XOR16_SHUFFLE
            else block
        )
        compressed = compression.zstd.compress(
            predicted,
            level=3,
            zstd_dict=prepared,
        )
        frame.extend(BLOCK_HEADER.pack(len(block), len(compressed)))
        frame.extend(compressed)
    return bytes(frame)


def decoded_size(frame: bytes) -> int:
    """Read a bounded declared length without materializing any compressed payload.

    Args:
        frame: A complete encoded value, with no legacy-format guessing.

    Returns:
        Its bounded original byte length; complete validation still requires decoding.

    Raises:
        ValueError: If the tag, declared length, or block count is invalid.
    """
    if frame[:1] == bytes([RAW_TAG]):
        size = len(frame) - 1
        if size <= MAX_DECODED_BYTES:
            return size
    elif len(frame) >= HEADER.size:
        tag, size, count = HEADER.unpack_from(frame)
        if (
            tag
            in {
                ZSTD_TAG,
                PREDICTED_TAG,
                ZSTD_TAG | DICTIONARY_FLAG,
                PREDICTED_TAG | DICTIONARY_FLAG,
            }
            and 0 < size <= MAX_DECODED_BYTES
            and count == (size + BLOCK_BYTES - 1) // BLOCK_BYTES
        ):
            return size
    message = "Invalid or oversized payload frame header"
    raise ValueError(message)


def dictionary_for(
    frame: bytes,
    dictionary: bytes | None,
) -> tuple[compression.zstd.ZstdDict | None, int]:
    """Resolve the frame's exact dictionary before any decompression allocation.

    Args:
        frame: The compressed frame with a validated tag.
        dictionary: The owning cache generation's dictionary, if available.

    Returns:
        The prepared dictionary and the first block's byte offset.

    Raises:
        ValueError: If required dictionary bytes are absent or have another identity.
    """
    if not frame[0] & DICTIONARY_FLAG:
        return None, HEADER.size
    position = HEADER.size + DICTIONARY_DIGEST_BYTES
    if (
        dictionary is None
        or frame[HEADER.size : position] != hashlib.sha256(dictionary).digest()
    ):
        message = "Payload compression dictionary is missing or changed"
        raise ValueError(message)
    return compression.zstd.ZstdDict(dictionary), position


def decompress_block(
    compressed: bytes,
    size: int,
    dictionary: compression.zstd.ZstdDict | None,
) -> bytes:
    """Reject oversized output, incomplete streams, and trailing compressed frames.

    Args:
        compressed: One complete bounded zstd frame.
        size: The exact expected output length after any predictor padding.
        dictionary: The validated optional dictionary.

    Returns:
        Exactly the expected block bytes.

    Raises:
        ValueError: If the compressed block differs from its complete framing contract.
    """
    decoder = compression.zstd.ZstdDecompressor(
        zstd_dict=dictionary,
        options={compression.zstd.DecompressionParameter.window_log_max: 20},
    )
    value = decoder.decompress(compressed, max_length=size + 1)
    if len(value) != size or not decoder.eof or decoder.unused_data:
        message = "Compressed block is truncated, oversized, or has trailing data"
        raise ValueError(message)
    return value


def decode(frame: bytes, *, dictionary: bytes | None = None) -> bytes:
    """Validate complete framing and reconstruct the exact original logical bytes.

    Args:
        frame: A versioned frame selected by explicit storage-format metadata.
        dictionary: The owning generation's optional immutable dictionary bytes.

    Returns:
        The original payload; callers still authenticate its logical checksum.

    Raises:
        ValueError: If framing, dictionaries, bounds, or compressed content are invalid.
    """
    total = decoded_size(frame)
    if frame[0] == RAW_TAG:
        return frame[1:]
    try:
        return decode_compressed(frame, dictionary, total)
    except compression.zstd.ZstdError as error:
        message = "Payload dictionary or compressed bytes are invalid"
        raise ValueError(message) from error


def decode_compressed(frame: bytes, dictionary: bytes | None, total: int) -> bytes:
    """Reconstruct blocks after their original size and count pass header validation.

    Args:
        frame: The complete compressed frame with a supported version tag.
        dictionary: The optional dictionary whose identity the header authenticates.
        total: Validated bounded original length.

    Returns:
        Exactly the original bytes when all block boundaries are valid.

    Raises:
        ValueError: If any block length, content, or trailing bytes are invalid.
    """
    prepared, position = dictionary_for(frame, dictionary)
    predicted = frame[0] & ~DICTIONARY_FLAG == PREDICTED_TAG
    result = bytearray()
    while len(result) < total:
        if position + BLOCK_HEADER.size > len(frame):
            message = "Payload block header is truncated"
            raise ValueError(message)
        size, compressed_size = BLOCK_HEADER.unpack_from(frame, position)
        position += BLOCK_HEADER.size
        if (
            size != min(BLOCK_BYTES, total - len(result))
            or not 0 < compressed_size <= MAX_ENCODED_BLOCK_BYTES
            or position + compressed_size > len(frame)
        ):
            message = "Payload block lengths are invalid"
            raise ValueError(message)
        stride = spatial_data.payload_prediction.STRIDE
        expected = ((size + stride - 1) // stride) * stride if predicted else size
        value = decompress_block(
            frame[position : position + compressed_size],
            expected,
            prepared,
        )
        position += compressed_size
        result.extend(
            spatial_data.payload_prediction.restore(value, size)
            if predicted
            else value,
        )
    if position != len(frame):
        message = "Payload frame has trailing bytes"
        raise ValueError(message)
    return bytes(result)
