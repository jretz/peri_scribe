"""Binary cache framing remains explicit, canonical, and non-executable."""

import struct
import sys
import textwrap

import pytest

import spatial_data.cache_values
import tests.formal.helpers.process
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


def test_primitive_cache_frames_work_without_scientific_libraries() -> None:
    result = tests.formal.helpers.process.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """\
                import sys

                import spatial_data.cache_values
                import spatial_data.payload_codec

                values = spatial_data.cache_values
                codec = spatial_data.payload_codec
                value = [None, False, 42, 0.25, "fire", b"data", {"groups": (1, 2)}]
                encoded = values.dumps(value)
                raw_frame = codec.encode(encoded)
                assert raw_frame[0] == codec.RAW_TAG
                assert values.loads(codec.decode(raw_frame)) == value
                compressed_frame = codec.encode(encoded * 100)
                assert compressed_frame[0] == codec.ZSTD_TAG
                assert codec.decode(compressed_frame) == encoded * 100
                invalid = values.MAGIC + values.HEADER.pack(values.TAGS["bool"], 0)
                try:
                    values.loads(invalid)
                except ValueError as error:
                    assert str(error) == "Invalid cache value"
                else:
                    raise AssertionError("Empty Boolean field was accepted")
                forbidden = {"numpy", "pandas", "pint", "shapely", "measurement_units"}
                assert not forbidden.intersection(sys.modules)
                """,
            ),
        ],
        timeout=10,
        can_start_nested_tools=False,
    )
    assert result.returncode == 0, result.stderr
