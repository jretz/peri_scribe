"""Rearrange exact bytes so nearby coordinate encodings compress together.

Design: [Exact compressed payloads](../../docs/algorithms/compressed-payloads.md).
"""

import numpy as np


STRIDE = 16


def predict(value: bytes) -> bytes:
    """XOR successive byte lanes and transpose them without interpreting coordinates.

    Args:
        value: One bounded original block, including arbitrary non-coordinate bytes.

    Returns:
        Predicted lanes padded to a complete stride; their original length is external.
    """
    padded = np.zeros(
        ((len(value) + STRIDE - 1) // STRIDE) * STRIDE,
        dtype=np.uint8,
    )
    padded[: len(value)] = np.frombuffer(value, dtype=np.uint8)
    predicted = padded.copy()
    predicted[STRIDE:] ^= padded[:-STRIDE]
    return predicted.reshape(-1, STRIDE).T.copy().tobytes()


def restore(value: bytes, original_size: int) -> bytes:
    """Invert lane order and cumulative XOR before removing declared padding.

    Args:
        value: Complete predicted lanes whose framing was validated by the caller.
        original_size: Exact number of original bytes before stride padding.

    Returns:
        The original bytes, including every coordinate and metadata bit.
    """
    lanes = np.frombuffer(value, dtype=np.uint8).reshape(STRIDE, -1).T
    original = np.bitwise_xor.accumulate(lanes, axis=0).reshape(-1)
    return original[:original_size].tobytes()
