"""Compress exact parsed payloads with one immutable dictionary per cache generation.

Design: [Exact compressed payloads](../../../docs/algorithms/compressed-payloads.md).
"""

import compression.zstd
import sqlite3

import spatial_data.payload_codec


DICTIONARY_BYTES = 16 * 1024
TRAINING_SAMPLES = 256
MAXIMUM_SAMPLE_BYTES = 64 * 1024
MAXIMUM_TRAINING_BYTES = 4 * 1024 * 1024
MINIMUM_TRAINING_SAMPLES = 8
MINIMUM_TRAINING_BYTES = 32 * 1024


def dictionaries(connection: sqlite3.Connection) -> dict[int, bytes]:
    """Load dictionary identities from the same transaction as their payload references.

    Args:
        connection: The pinned parsed-cache transaction.

    Returns:
        Small immutable dictionaries keyed by their generation-local identity.

    Raises:
        ValueError: If a stored dictionary is not bytes, allowing source fallback.
    """
    values = dict(connection.execute("SELECT id, value FROM codec_dictionaries"))
    if any(not isinstance(value, bytes) for value in values.values()):
        message = "Parsed compression dictionary must contain bytes"
        raise ValueError(message)
    return values


def decode(
    value: bytes | str,
    encoding: int,
    original_size: int,
    *,
    dictionary: bytes | None = None,
    text: bool = False,
) -> bytes | str:
    """Interpret explicit format metadata and validate the canonical byte count.

    Args:
        value: Stored payload, including supported uncompressed encodings.
        encoding: Zero for raw logical content, one for the bounded shared codec.
        original_size: Stored logical byte count used by admission scheduling.
        dictionary: Immutable dictionary selected by this payload's reference.
        text: Whether the logical value is exact UTF-8 text.

    Returns:
        Original geometry bytes or attribute text, ready for checksum validation.

    Raises:
        ValueError: If encoding, type, declared length, or text bytes are invalid.
    """
    if encoding == 1 and isinstance(value, bytes):
        original = spatial_data.payload_codec.decode(value, dictionary=dictionary)
    elif encoding == 0 and isinstance(value, str if text else bytes):
        original = value.encode() if isinstance(value, str) else value
    else:
        message = "Parsed dictionary payload has an invalid stored digest encoding"
        raise ValueError(message)
    if len(original) != original_size:
        message = "Parsed dictionary payload size disagrees with its stored digest"
        raise ValueError(message)
    return original.decode() if text else original


def encode(
    value: bytes | str,
    *,
    dictionary: bytes | None = None,
) -> tuple[bytes | str, int, int]:
    """Keep optional cache limits from restricting authoritative source payloads.

    Args:
        value: Exact source geometry bytes or canonical attribute text.
        dictionary: Optional immutable dictionary for attribute compression.

    Returns:
        Stored content, its explicit encoding marker, and the original byte length.
    """
    original = value.encode() if isinstance(value, str) else value
    predictor = (
        spatial_data.payload_codec.Predictor.NONE
        if isinstance(value, str)
        else spatial_data.payload_codec.Predictor.XOR16_SHUFFLE
    )
    try:
        encoded = spatial_data.payload_codec.encode(
            original,
            dictionary=dictionary,
            predictor=predictor,
        )
    except ValueError:
        return value, 0, len(original)
    return encoded, 1, len(original)


def training_samples(connection: sqlite3.Connection) -> list[bytes]:
    """Bound deterministic sparse training independently of the full feed size.

    Args:
        connection: The transaction containing the complete attribute dictionary.

    Returns:
        At most 256 samples totaling at most four MiB in ascending payload identity.
    """
    count = connection.execute("SELECT count(*) FROM attribute_payloads").fetchone()[0]
    step = max(1, (count + TRAINING_SAMPLES - 1) // TRAINING_SAMPLES)
    samples: list[bytes] = []
    total = 0
    for index, row in enumerate(
        connection.execute(
            "SELECT value, encoding, original_size FROM attribute_payloads ORDER BY id",
        ),
    ):
        if index % step:
            continue
        value = decode(*row, text=True)
        original = str(value).encode()[:MAXIMUM_SAMPLE_BYTES]
        sample = original[: MAXIMUM_TRAINING_BYTES - total]
        samples.append(sample)
        total += len(sample)
        if total == MAXIMUM_TRAINING_BYTES:
            break
    return samples


def prepare_dictionary(connection: sqlite3.Connection) -> None:
    """Publish a dictionary and every referring value in the writer's transaction.

    A cache generation trains at most one immutable dictionary. New schemas and small
    feeds still use exact zstd framing when dictionary training is not worthwhile.

    Args:
        connection: The transaction also publishing source receipts and row references.
    """
    if dictionaries(connection):
        return
    samples = training_samples(connection)
    if (
        len(samples) < MINIMUM_TRAINING_SAMPLES
        or sum(map(len, samples)) < MINIMUM_TRAINING_BYTES
    ):
        return
    try:
        dictionary = compression.zstd.train_dict(samples, DICTIONARY_BYTES).dict_content
    except compression.zstd.ZstdError:
        return
    connection.execute(
        "INSERT INTO codec_dictionaries (id, value) VALUES (1, ?)",
        (dictionary,),
    )
    for identifier, value, encoding, original_size in connection.execute(
        "SELECT id, value, encoding, original_size FROM attribute_payloads ORDER BY id",
    ):
        logical = decode(value, encoding, original_size, text=True)
        stored, marker, size = encode(logical, dictionary=dictionary)
        connection.execute(
            "UPDATE attribute_payloads SET value = ?, encoding = ?, "
            "original_size = ?, dictionary_id = 1 WHERE id = ?",
            (stored, marker, size, identifier),
        )
