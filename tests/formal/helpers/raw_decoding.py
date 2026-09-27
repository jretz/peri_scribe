"""Raw feed fixtures and adapters for the compiled typed-decoding specification."""

from __future__ import annotations

import dataclasses
import datetime
import itertools
import struct
import typing

import numpy as np
import pandas as pd

import peri_scribe.perimeters.versions
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.perimeters.versions


if typing.TYPE_CHECKING:
    import collections.abc

EPOCH = datetime.datetime(1970, 1, 1)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Candidate:
    """Pair a raw representation with its independently constructed semantic input."""

    raw: object
    encoded: str
    present: bool = True


def bits(value: float) -> int:
    """Keep even signed zero and subnormal payloads distinguishable in the oracle.

    Args:
        value: A finite binary64 value.

    Returns:
        Its unsigned bit pattern, used as an opaque Lean value identity.
    """
    return int.from_bytes(struct.pack(">d", value))


def ticks(value: datetime.datetime) -> int:
    """Encode a wall-clock reading exactly without another timezone conversion.

    Args:
        value: A calendar reading, whose timezone is represented separately.

    Returns:
        Calendar microseconds from the Unix epoch.
    """
    delta = value.replace(tzinfo=None) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def numeric_candidates() -> tuple[Candidate, ...]:
    """Exercise raw missing, malformed, Boolean, finite, and nonfinite categories.

    Returns:
        Numeric field representations with finite payloads fixed before parsing.
    """
    cases = [
        Candidate(raw=None, encoded="missing", present=False),
        Candidate(raw=None, encoded="missing"),
        Candidate(raw=pd.NA, encoded="missing"),
        Candidate(raw="", encoded="malformed"),
        Candidate(raw="bad", encoded="malformed"),
        Candidate(raw=True, encoded="boolean"),
        Candidate(raw="NaN", encoded="nonfinite"),
        Candidate(raw="Infinity", encoded="nonfinite"),
        Candidate(raw=0, encoded=f"value:{bits(0.0)}"),
        Candidate(raw="-0.0", encoded=f"value:{bits(-0.0)}"),
        Candidate(raw="12.5", encoded=f"value:{bits(12.5)}"),
        Candidate(raw="-2.5", encoded=f"value:{bits(-2.5)}"),
    ]
    cases.extend(Candidate(raw=value, encoded="missing") for value in [pd.NaT, np.nan])
    cases.extend(
        Candidate(raw=value, encoded="malformed")
        for value in ["   ", "1,000", "0x10", [], {}, b"1", 10**1000]
    )
    cases.extend(
        Candidate(raw=value, encoded="boolean") for value in [False, np.bool_(1)]
    )
    cases.extend(
        Candidate(raw=value, encoded="nonfinite")
        for value in [float("inf"), float("-inf"), "-Infinity", "1e9999"]
    )
    for value in [0.0, -0.0, 0.25, -0.25, 1e-300, 5e-324, 1e300]:
        cases.extend(
            Candidate(raw=raw, encoded=f"value:{bits(value)}")
            for raw in [value, str(value), f" \t{value}\n", np.float64(value)]
        )
    cases.append(Candidate(raw=np.int64(7), encoded=f"value:{bits(7.0)}"))
    return tuple(cases)


def text_candidates() -> tuple[Candidate, ...]:
    """Distinguish missing and blank values from usable stripped source labels.

    Returns:
        Raw text fields, with encoded values indexing their canonical labels.
    """
    cases = [
        Candidate(raw=None, encoded="missing", present=False),
        Candidate(raw=None, encoded="missing"),
        Candidate(raw=pd.NA, encoded="missing"),
        Candidate(raw=pd.NaT, encoded="missing"),
        Candidate(raw=np.nan, encoded="missing"),
        Candidate(raw="", encoded="malformed"),
        Candidate(raw=" \t\n", encoded="malformed"),
        Candidate(raw="\u2003", encoded="malformed"),
        Candidate(raw="FIRIS", encoded="value:1"),
        Candidate(raw=" FIRIS ", encoded="value:1"),
        Candidate(raw="WFIGS", encoded="value:2"),
        Candidate(raw=" \tWFIGS\n", encoded="value:2"),
    ]
    cases.extend([
        Candidate(raw="\u2003FIRIS\u2003", encoded="value:1"),
        Candidate(raw="A B", encoded="value:3"),
        Candidate(raw=" A B ", encoded="value:3"),
        Candidate(raw=0, encoded="value:4"),
        Candidate(raw="0", encoded="value:4"),
        Candidate(raw=True, encoded="value:5"),
    ])
    return tuple(cases)


def time_candidates(*, epoch_milliseconds: bool) -> tuple[Candidate, ...]:
    """Construct calendar and epoch representations with independent integer inputs.

    Args:
        epoch_milliseconds: Whether the feed accepts ArcGIS numeric date fields.

    Returns:
        Raw timestamps, including invalid syntax and UTC range overflow.
    """
    cases = [
        Candidate(raw=None, encoded="invalid", present=False),
        Candidate(raw=None, encoded="invalid"),
        Candidate(raw=pd.NA, encoded="invalid"),
        Candidate(raw=pd.NaT, encoded="invalid"),
        Candidate(raw="", encoded="invalid"),
        Candidate(raw="bad", encoded="invalid"),
        Candidate(raw=True, encoded="invalid"),
        Candidate(raw="2026-02-30", encoded="invalid"),
        Candidate(raw="1970-01-01T00:00:00Z", encoded="wall:0:0"),
        Candidate(
            raw="1970-01-01T01:00:00+01:00",
            encoded="wall:3600000000:3600000000",
        ),
        Candidate(raw="1970-01-01T00:00:01", encoded="wall:1000000:0"),
        Candidate(raw="1969-12-31T23:59:59Z", encoded="wall:-1000000:0"),
    ]
    cases.extend(
        Candidate(raw=value, encoded="invalid")
        for value in [np.nan, False, [], {}, "10000-01-01", "2026-01-01T00:00:00+24:00"]
    )
    for wall in [
        datetime.datetime.min,
        datetime.datetime.max,
        datetime.datetime(2000, 2, 29, 12, 30, 1, 123456),
        datetime.datetime(2026, 9, 26, 13, 45, 2, 999999),
    ]:
        cases.extend(
            Candidate(raw=raw, encoded=f"wall:{ticks(wall)}:0")
            for raw in [wall, wall.isoformat(), f" {wall.isoformat()} "]
        )
        for seconds in [-50400, -25200, 0, 19800, 50400]:
            aware = wall.replace(
                tzinfo=datetime.timezone(
                    datetime.timedelta(seconds=seconds),
                ),
            )
            cases.extend(
                Candidate(raw=raw, encoded=f"wall:{ticks(wall)}:{seconds * 1000000}")
                for raw in [aware, aware.isoformat()]
            )
    cases.append(
        Candidate(
            raw=pd.Timestamp("2026-09-26T00:00:00Z"),
            encoded=f"wall:{ticks(datetime.datetime(2026, 9, 26))}:0",
        ),
    )
    for value in [
        0,
        1,
        -1,
        1755691200123,
        -62135596800000,
        253402300799000,
        -62135596801000,
        253402300800000,
        10**1000,
    ]:
        cases.extend(
            Candidate(
                raw=raw,
                encoded=f"milliseconds:{value}" if epoch_milliseconds else "invalid",
            )
            for raw in ([value] if value == 10**1000 else [value, float(value)])
        )
    cases.extend(
        Candidate(raw=value, encoded="invalid")
        for value in [float("inf"), float("-inf"), "Infinity", "NaN"]
    )
    return tuple(cases)


def sequences(candidates: tuple[Candidate, ...]) -> list[tuple[Candidate, ...]]:
    """Vary field priority independently of every raw representation.

    Args:
        candidates: Typed raw representations, beginning with twelve core cases.

    Returns:
        Empty, singleton, exhaustive core triples, and broad fallback sequences.
    """
    core = candidates[:12]
    return [
        (),
        *((candidate,) for candidate in candidates),
        *itertools.product(core, repeat=3),
        *((core[5], core[6], candidate, core[10]) for candidate in candidates),
        *((candidate, core[10], core[11]) for candidate in candidates),
    ]


def attributes(
    values: tuple[Candidate, ...],
) -> tuple[dict[str, object], tuple[str, ...]]:
    """Keep declared priority independent of dictionary insertion order.

    Args:
        values: Candidate fields in semantic priority order.

    Returns:
        A reversed-insertion row and its declared column ordering.
    """
    columns = tuple(f"column_{index}" for index in range(len(values)))
    return {
        column: candidate.raw
        for column, candidate in reversed(tuple(zip(columns, values, strict=True)))
        if candidate.present
    }, columns


def result(value: object) -> tuple[int, ...]:
    """Encode implementation results without repeating field-selection policy.

    Args:
        value: An actual parser or typed-selector result.

    Returns:
        Presence and the exact value encoded consumed by the oracle protocol.
    """
    if value is None:
        return (0,)
    if isinstance(value, datetime.datetime):
        assert value.utcoffset() == datetime.timedelta()
        return 1, ticks(value)
    if isinstance(value, float):
        return 1, bits(value)
    assert isinstance(value, str)
    return 1, {"FIRIS": 1, "WFIGS": 2, "A B": 3, "0": 4, "True": 5}[value]


def check_fields(
    candidates: tuple[Candidate, ...],
    selector: collections.abc.Callable[..., object],
    *,
    operation: str,
) -> int:
    """Compare complete typed selections with the executable proved definition.

    Args:
        candidates: Raw values and independent semantic inputs.
        selector: The production typed field selector.
        operation: The oracle's typed-values or UTC-normalization operation.

    Returns:
        The number of priority sequences checked.
    """
    cases = sequences(candidates)
    expected = tests.formal.helpers.oracle.evaluate(
        [f"{operation}|" + " ".join(item.encoded for item in case) for case in cases],
        executable="oracleRawDecoding",
    )
    for case, reference in zip(cases, expected, strict=True):
        row, columns = attributes(case)
        assert result(selector(row, *columns)) == reference, case
    return len(cases)


def check_scalars(
    candidates: tuple[Candidate, ...],
    parser: collections.abc.Callable[[object], object],
    *,
    operation: str,
) -> int:
    """Exercise raw lexical forms through the same scalar parser used by feeds.

    Args:
        candidates: Independently constructed raw and semantic representations.
        parser: The actual scalar parser.
        operation: The relevant executable oracle operation.

    Returns:
        The number of raw representations checked.
    """
    expected = tests.formal.helpers.oracle.evaluate(
        [f"{operation}|{candidate.encoded}" for candidate in candidates],
        executable="oracleRawDecoding",
    )
    for candidate, reference in zip(candidates, expected, strict=True):
        assert result(parser(candidate.raw)) == reference, candidate
    return len(candidates)


def check_effective_times() -> int:
    """Bind typed timestamp fallback to actual perimeter chronology selection.

    Returns:
        The number of row and snapshot priority combinations checked.
    """
    candidates = time_candidates(epoch_milliseconds=True)[:12]
    current = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)
    cases = list(itertools.product(candidates, candidates, [None, current]))
    commands = [
        "times|"
        + " ".join([
            first.encoded,
            second.encoded,
            "invalid" if snapshot is None else f"wall:{ticks(snapshot)}:0",
        ])
        for first, second, snapshot in cases
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oracleRawDecoding",
    )
    for (first, second, snapshot), reference in zip(cases, expected, strict=True):
        observation = (
            tests.helpers.factories.peri_scribe.perimeters.versions.observation(
                attributes={
                    "EditDate": first.raw,
                    "attr_ModifiedOnDateTime_dt": second.raw,
                },
                snapshot_time=snapshot,
            )
        )
        assert result(peri_scribe.perimeters.versions.effective_time(observation)) == (
            reference
        )
    return len(cases)
