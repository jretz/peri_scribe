import pathlib
import struct

import pytest

import tests.formal.check
import tests.formal.helpers.corpus
import tests.formal.helpers.model_registry
import tests.formal.helpers.session
import tests.formal.helpers.tlc
import tests.formal.helpers.tlc_frame_wire
import tests.formal.helpers.tlc_frames
import tests.formal.helpers.tlc_worker


FRAMES = (
    b"F\teA==\nV\t0\tMA==\tMQ==\nI\t0\n"
    b"S\t0\t0\nE\t0\tAdvance\t1\nE\t0\tAdvance\t1\n"
    b"S\t1\t1\nC\t3\t2\t1\t2\n"
)


def test_ranked_eventualities_publish_complete_registered_graphs(
    tmp_path: pathlib.Path,
) -> None:
    for module in ("OrderedWorkers", "FetchCrash"):
        assert (
            tests.formal.helpers.model_registry.exports()[module, module]
            is tests.formal.helpers.model_registry.Export.GRAPH
        )
        assert tests.formal.helpers.tlc_frames.path(tmp_path, module, module) == (
            tmp_path / f"frames-{module}.pfr"
        )
        assert (
            tests.formal.helpers.tlc_frames.path(tmp_path, module, "Unreviewed") is None
        )


def test_read_frame_receipt_keeps_duplicate_edges(
    tmp_path: pathlib.Path,
) -> None:
    file = tmp_path / "frames.tsv"
    file.write_bytes(FRAMES)
    graph = tests.formal.helpers.tlc_frames.read(file).graph()
    assert graph.states == {0: {"x": "0"}, 1: {"x": "1"}}
    assert graph.initial == frozenset({0})
    assert graph.outgoing == {
        0: (tests.formal.helpers.tlc.Edge(source=0, target=1, action="Advance"),) * 2,
    }


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        (b"C\t3\t2\t1\t2\n", b""),
        (b"C\t3\t2\t1\t2\n", b"C\t2\t2\t1\t1\n"),
        (b"E\t0\tAdvance\t1\n", b"E\t0\tAdvance\t0\n"),
        (b"E\t0\tAdvance\t1\n", b"E\t0\tAdvance\t3\n"),
        (b"S\t1\t1\n", b"S\t1\t0\n"),
    ],
)
def test_read_frame_receipt_rejects_invalid_graph(
    tmp_path: pathlib.Path,
    original: bytes,
    replacement: bytes,
) -> None:
    file = tmp_path / "frames.tsv"
    file.write_bytes(FRAMES.replace(original, replacement))
    with pytest.raises((AssertionError, ValueError)):
        tests.formal.helpers.tlc_frames.read(file)


def packed_frame(*, with_edges: bool = True) -> bytes:
    """Encode two states with duplicate successors in the graph mode.

    Args:
        with_edges: Whether the receipt includes the ordered graph edges.

    Returns:
        A complete binary frame receipt for the reader checks.
    """
    return b"".join((
        struct.pack(">4s?4IB", b"PFR2", with_edges, 3, 2, 1, 2, 1),
        b"\0\0\0\1x\0\2\0\0\0\0010\0\0\0\0011",
        struct.pack(">2H", 0, 1),
        (
            b"\1\0\0\0\7Advance" + struct.pack(">4I2B", 2, 0, 1, 1, 0, 0)
            if with_edges
            else b""
        ),
    ))


def test_packed_receipt_keeps_ordered_occurrences_and_exact_projection(
    tmp_path: pathlib.Path,
) -> None:
    original = tmp_path / "legacy.tsv"
    original.write_bytes(FRAMES)
    packed = tmp_path / "frames.pfr"
    packed.write_bytes(packed_frame())
    frames = tests.formal.helpers.tlc_frames
    receipt = frames.read(packed)
    assert receipt.graph() == frames.read(original).graph()
    assert receipt.states() == [{"x": "0"}, {"x": "1"}]
    assert isinstance(receipt, tests.formal.helpers.tlc_frame_wire.Receipt)
    projected = receipt.projected(("x",), where=("x", frozenset({"1"})))
    assert list(projected) == [{"x": "1"}]
    assert receipt.rows.readonly


def test_state_only_packed_receipt_cannot_supply_graph(
    tmp_path: pathlib.Path,
) -> None:
    packed = tmp_path / "frames.pfr"
    packed.write_bytes(packed_frame(with_edges=False))
    assert tests.formal.helpers.tlc_frames.read(packed, with_edges=False).states() == [
        {"x": "0"},
        {"x": "1"},
    ]
    with pytest.raises(AssertionError, match="state-only"):
        tests.formal.helpers.tlc_frames.read(packed)


@pytest.mark.parametrize(
    ("offset", "replacement"),
    [
        (-1, 2),  # Unknown action code.
        (-3, 3),  # Unknown target.
        (-3, 0),  # Removing both forward edges loses the discovery witness.
        (-11, 1),  # Degrees disagree with the checked footer.
        (42, 2),  # Unknown state value.
        (42, 0),  # Duplicate state row.
    ],
)
def test_malformed_packed_receipt_rejects_codes_and_witnesses(
    tmp_path: pathlib.Path,
    offset: int,
    replacement: int,
) -> None:
    raw = bytearray(packed_frame())
    final_target = -3
    raw[offset] = replacement
    if offset == final_target and replacement == 0:
        raw[-7] = 0
    packed = tmp_path / "frames.pfr"
    packed.write_bytes(raw)
    with pytest.raises(AssertionError):
        tests.formal.helpers.tlc_frames.read(packed)


@pytest.mark.parametrize("ending", [b"", b"\nextra"])
def test_packed_receipt_rejects_incomplete_or_trailing_bytes(
    tmp_path: pathlib.Path,
    ending: bytes,
) -> None:
    packed = tmp_path / "frames.pfr"
    packed.write_bytes(packed_frame()[:-1] + ending)
    with pytest.raises(AssertionError):
        tests.formal.helpers.tlc_frames.read(packed)


@pytest.mark.asyncio
async def test_run_model_checks_changed_source_with_standard_tlc(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(tests.formal.helpers.session.VARIABLE, raising=False)
    java, jar = tests.formal.check.toolchain()
    (tmp_path / "FeedCoordinator.tla").write_text(
        "---- MODULE FeedCoordinator ----\n"
        "EXTENDS Naturals\n"
        "VARIABLES x, y\n"
        "variables == <<x, y>>\n"
        "Init == x = 0 /\\ y = 0\n"
        "Next == x = 0 /\\ x' = 1 /\\ UNCHANGED y\n"
        "Spec == Init /\\ [][Next]_variables\n"
        "Safe == x \\in 0..1\n"
        "====\n",
    )
    (tmp_path / "FeedCoordinator.cfg").write_text(
        "SPECIFICATION Spec\nINVARIANT Safe\nCHECK_DEADLOCK FALSE\n",
    )
    classes = await tests.formal.helpers.tlc_worker.compile_worker(
        java,
        tmp_path,
        jar=jar,
    )
    worker = tests.formal.helpers.tlc_worker.Worker(java, jar, classes, tmp_path)
    model = tests.formal.check.Model(
        name="changed-feed",
        module="FeedCoordinator",
        config="FeedCoordinator",
        conformance=tests.formal.helpers.model_registry.Export.STATES,
    )
    try:
        assert await tests.formal.check.run_model(
            model,
            java,
            jar,
            tmp_path,
            worker=worker,
        )
    finally:
        await worker.close()
    assert not (tmp_path / "frames-FeedCoordinator.pfr").exists()
    assert tests.formal.helpers.corpus.states(
        "FeedCoordinator",
        "FeedCoordinator",
        tmp_path,
    ) == [{"x": "0", "y": "0"}, {"x": "1", "y": "0"}]
