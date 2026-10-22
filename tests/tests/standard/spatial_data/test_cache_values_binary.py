"""Binary cache framing remains explicit, canonical, and non-executable."""

import struct

import pytest

import spatial_data.cache_values
import tests.helpers.factories.spatial_data.cache_values


@pytest.mark.parametrize(
    "payload",
    tests.helpers.factories.spatial_data.cache_values.invalid_values(),
)
def test_loads_rejects_invalid_binary_shapes_and_contents(payload: bytes) -> None:
    with pytest.raises(ValueError, match=r".+"):
        spatial_data.cache_values.loads(payload)


def test_dumps_preserves_raw_float_and_byte_evidence() -> None:
    bits = bytes.fromhex("7ff8000000000007")
    value = struct.unpack("!d", bits)[0]
    payload = spatial_data.cache_values.dumps((value, b"\x00\xff"))
    assert (
        payload
        == b"PSCV\x02"
        + tests.helpers.factories.spatial_data.cache_values.node(
            8,
            tests.helpers.factories.spatial_data.cache_values.node(5, bits)
            + tests.helpers.factories.spatial_data.cache_values.node(7, b"\x00\xff"),
        )
    )


@pytest.mark.parametrize("suffix", [b"\0", b"PSCV\x02"])
def test_loads_rejects_trailing_binary_data(suffix: bytes) -> None:
    with pytest.raises(ValueError, match="noncanonical"):
        spatial_data.cache_values.loads(spatial_data.cache_values.dumps(None) + suffix)
