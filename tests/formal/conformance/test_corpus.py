import asyncio
import pathlib
import unittest.mock

import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.corpus_checks
import tests.formal.helpers.process
import tests.formal.helpers.session
import tests.formal.helpers.tlc


def test_load_publishes_one_complete_corpus_for_concurrent_processes(
    tmp_path: pathlib.Path,
) -> None:
    attempts = tmp_path / "attempts"
    results = asyncio.run(
        asyncio.wait_for(
            tests.formal.helpers.corpus_checks.concurrent(
                tmp_path / "session",
                attempts,
            ),
            timeout=20,
        ),
    )
    for result in results:
        assert result.returncode == 0, result.stdout + result.stderr
        assert tests.formal.helpers.corpus_checks.ADAPTER.validate_json(
            result.stdout,
        ) == tests.formal.helpers.corpus_checks.Sample(producer="held")
    directories = [pathlib.Path(value) for value in attempts.read_text().splitlines()]
    assert len(directories) == 1
    assert not directories[0].exists()


def test_load_retries_after_failed_generation_without_reusing_partial_inputs(
    tmp_path: pathlib.Path,
) -> None:
    attempts = tmp_path / "attempts"
    session = tmp_path / "session"
    with pytest.raises(ValueError, match="corpus generation failed"):
        tests.formal.helpers.corpus.load(
            session,
            "sample",
            tests.formal.helpers.corpus_checks.ADAPTER,
            tests.formal.helpers.corpus_checks.Producer(
                attempts=attempts,
                behavior="raise",
            ).build,
        )
    result = tests.formal.helpers.corpus.load(
        session,
        "sample",
        tests.formal.helpers.corpus_checks.ADAPTER,
        tests.formal.helpers.corpus_checks.Producer(attempts=attempts).build,
    )
    assert result == tests.formal.helpers.corpus_checks.Sample(producer="success")
    failed, completed = (
        pathlib.Path(value) for value in attempts.read_text().splitlines()
    )
    assert failed != completed
    assert not failed.exists()
    assert not completed.exists()


def test_load_retries_after_process_termination_releases_the_writer_lock(
    tmp_path: pathlib.Path,
) -> None:
    attempts = tmp_path / "attempts"
    session = tmp_path / "session"
    interrupted = tests.formal.helpers.process.run(
        tests.formal.helpers.corpus_checks.command(session, attempts, "exit"),
        timeout=20,
    )
    assert interrupted.returncode == (
        tests.formal.helpers.corpus_checks.INTERRUPTED_EXIT
    ), interrupted.stdout + interrupted.stderr
    recovered = tests.formal.helpers.process.run(
        tests.formal.helpers.corpus_checks.command(session, attempts, "success"),
        timeout=20,
    )
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert tests.formal.helpers.corpus_checks.ADAPTER.validate_json(
        recovered.stdout.splitlines()[-1],
    ) == tests.formal.helpers.corpus_checks.Sample(producer="success")
    failed, completed = (
        pathlib.Path(value) for value in attempts.read_text().splitlines()
    )
    assert failed != completed
    assert not completed.exists()


def test_load_reuses_only_the_current_test_session_corpus(
    tmp_path: pathlib.Path,
) -> None:
    attempts = tmp_path / "attempts"
    sessions = (tmp_path / "first-session", tmp_path / "second-session")
    for session in sessions:
        result = tests.formal.helpers.corpus.load(
            session,
            "sample",
            tests.formal.helpers.corpus_checks.ADAPTER,
            tests.formal.helpers.corpus_checks.Producer(attempts=attempts).build,
        )
        cached = tests.formal.helpers.corpus.load(
            session,
            "sample",
            tests.formal.helpers.corpus_checks.ADAPTER,
            tests.formal.helpers.corpus_checks.Producer(
                attempts=attempts,
                behavior="raise",
            ).build,
        )
        assert result == cached
    assert len(attempts.read_text().splitlines()) == len(sessions)


def test_graph_reuse_preserves_exact_nodes_fields_and_successor_iteration_order(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(tests.formal.helpers.session.VARIABLE, raising=False)
    first = (1 << 63) - 5
    second = -(1 << 63) + 7
    third = 17
    expected = tests.formal.helpers.tlc.Graph(
        states={
            first: {
                "phase": '"ready"',
                "pending": '[remaining |-> <<"geography", "kmz">>, forced |-> TRUE]',
                "action": '"begin:0:3:True:False:True:False"',
            },
            second: {"action": '"crash"', "phase": '"done"'},
            third: {"phase": '"done"', "action": '"acknowledge"'},
        },
        initial=frozenset({first, second}),
        outgoing={
            third: (),
            first: (
                tests.formal.helpers.tlc.Edge(
                    source=first,
                    target=third,
                    action="Execute",
                ),
                tests.formal.helpers.tlc.Edge(
                    source=first,
                    target=second,
                    action="Crash",
                ),
                tests.formal.helpers.tlc.Edge(
                    source=first,
                    target=third,
                    action="Acknowledge",
                ),
            ),
            second: (
                tests.formal.helpers.tlc.Edge(
                    source=second,
                    target=third,
                    action="Execute",
                ),
            ),
        },
    )
    producer = unittest.mock.create_autospec(
        tests.formal.helpers.tlc.checked_graph,
        return_value=tests.formal.helpers.tlc.CheckedGraph(
            graph=expected,
            output="checked",
        ),
    )
    monkeypatch.setattr(tests.formal.helpers.tlc, "checked_graph", producer)
    cold = tests.formal.helpers.corpus.graph("Example", "Bounded", tmp_path)
    reused = tests.formal.helpers.corpus.graph("Example", "Bounded", tmp_path)
    producer.assert_called_once()
    assert producer.call_args.args[:2] == ("Example", "Bounded")
    assert cold == reused == expected
    assert tuple(
        (node, tuple(fields.items())) for node, fields in reused.states.items()
    ) == tuple(
        (node, tuple(fields.items())) for node, fields in expected.states.items()
    )
    assert tuple(reused.outgoing.items()) == tuple(expected.outgoing.items())


@pytest.mark.asyncio
async def test_checked_graph_releases_cancelled_producer_without_publishing(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = tests.formal.helpers.tlc.CheckedGraph(
        graph=tests.formal.helpers.tlc.Graph(
            states={1: {"phase": '"done"'}},
            initial=frozenset({1}),
            outgoing={},
        ),
        output="checked",
    )
    producer = unittest.mock.AsyncMock(side_effect=[asyncio.CancelledError, expected])
    monkeypatch.setattr(tests.formal.helpers.tlc, "checked_graph_async", producer)
    with pytest.raises(asyncio.CancelledError):
        await tests.formal.helpers.corpus.checked_graph("Example", "Bounded", tmp_path)
    assert not (tmp_path / "graph-Example-Bounded.json").exists()
    assert (
        await tests.formal.helpers.corpus.checked_graph(
            "Example",
            "Bounded",
            tmp_path,
        )
        == expected
    )
    assert (
        await tests.formal.helpers.corpus.checked_graph(
            "Example",
            "Bounded",
            tmp_path,
        )
        == expected
    )
    attempts = 2
    assert producer.await_count == attempts
