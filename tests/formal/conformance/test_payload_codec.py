"""The vectorized byte layout agrees with the executable proved lane definitions."""

import hashlib

import spatial_data.payload_codec
import spatial_data.payload_prediction
import tests.formal.helpers.oracle


def test_predictor_and_reconstruction_match_checked_lean_byte_lanes() -> None:
    values = [
        bytes((index * 17 + offset) % 256 for index in range(length))
        for length in range(66)
        for offset in (0, 1, 255)
    ]
    values.extend(
        b"".join(hashlib.sha256(str(index).encode()).digest() for index in range(count))
        for count in (4, 16, 32)
    )
    expected = tests.formal.helpers.oracle.evaluate(
        [" ".join(map(str, (16, *value))) for value in values],
        executable="oraclePayloadCodec",
    )
    for original, lanes in zip(values, expected, strict=True):
        encoded = spatial_data.payload_prediction.predict(original)
        assert encoded == bytes(lanes)
        assert (
            spatial_data.payload_prediction.restore(encoded, len(original)) == original
        )
        frame = spatial_data.payload_codec.encode(
            original,
            predictor=spatial_data.payload_codec.Predictor.XOR16_SHUFFLE,
        )
        assert spatial_data.payload_codec.decode(frame) == original
