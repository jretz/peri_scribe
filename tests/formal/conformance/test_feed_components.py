"""Require native fallback and actual delegation checks at the component boundary."""

import collections.abc
import datetime
import pathlib

import pytest

import peri_scribe.durable_file
import peri_scribe.pipeline_state
import peri_scribe.sources.feed_types
import peri_scribe.sources.fetch_control
import peri_scribe.sources.fetching
import tests.formal.helpers.feed_component_binding
import tests.formal.helpers.feed_components
import tests.formal.helpers.feed_coordinator
import tests.formal.helpers.pipeline_replay_files


@pytest.fixture(scope="module")
def native_collection(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[
    tests.formal.helpers.feed_coordinator.Case,
    tests.formal.helpers.feed_components.Receipt,
    tests.formal.helpers.feed_coordinator.Outcome,
]:
    """Build immutable input through a real native wave in the current test run.

    Returns:
        The independently captured current case, joined values and facade observation.
    """
    case = tests.formal.helpers.feed_coordinator.Case(
        kinds=("same", "same", "same"),
        full=False,
        prior=False,
        index_failure=False,
        deferred=False,
    )
    probe = tests.formal.helpers.feed_components.NativeProbe(
        case=case,
        directory=tmp_path_factory.mktemp("native-feed-cut") / "data" / "2026",
    )
    observed = probe.run()
    return case, probe.receipt(), observed


@pytest.mark.parametrize(
    "unsupported",
    ["adapter", "collector", "reader", "reader-source", "namespace", "proof", "source"],
)
def test_unknown_component_uses_complete_native_replay(
    unsupported: str,
    native_collection: tuple[
        tests.formal.helpers.feed_coordinator.Case,
        tests.formal.helpers.feed_components.Receipt,
        tests.formal.helpers.feed_coordinator.Outcome,
    ],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = tests.formal.helpers.feed_component_binding
    case, receipt, observed = native_collection
    match unsupported:
        case "adapter":
            original = peri_scribe.durable_file.LocalFile.replace_text

            def replace(file: peri_scribe.durable_file.LocalFile, text: str) -> None:
                """Preserve native effects with an unqualified executable."""
                original(file, text)

            monkeypatch.setattr(
                peri_scribe.durable_file.LocalFile,
                "replace_text",
                replace,
            )
        case "collector":
            original_collect = peri_scribe.sources.fetching.collect_feed_outcomes

            def collect(
                fetch: collections.abc.Callable[
                    [peri_scribe.sources.feed_types.Feed],
                    peri_scribe.sources.fetching.FeedOutcome,
                ],
            ) -> tuple[peri_scribe.sources.fetching.FeedOutcome, ...]:
                """Run genuine workers with an unqualified collector binding.

                Returns:
                    The actual complete native result.
                """
                return original_collect(fetch)

            monkeypatch.setattr(
                peri_scribe.sources.fetching,
                "collect_feed_outcomes",
                collect,
            )
            module, digest, names = binding.SOURCES[0]
            assert not binding.reviewed(module, digest, names)
        case "reader":
            original_read = peri_scribe.pipeline_state.read_state

            def read(
                directory: pathlib.Path,
            ) -> peri_scribe.pipeline_state.PendingRun:
                """Preserve native reader behavior with an unqualified executable.

                Returns:
                    The current state read through the actual native file adapter.
                """
                return original_read(directory)

            monkeypatch.setattr(peri_scribe.pipeline_state, "read_state", read)
            module, digest, names = next(
                entry
                for entry in binding.SOURCES
                if entry[0] is peri_scribe.pipeline_state
            )
            assert not binding.reviewed(module, digest, names)
        case "reader-source":
            source = pathlib.Path(peri_scribe.pipeline_state.__file__)
            changed = tmp_path / "unreviewed-reader.py"
            changed.write_text(
                source.read_text(encoding="utf-8") + "\nUNREVIEWED_READER = True\n",
                encoding="utf-8",
            )
            monkeypatch.setattr(peri_scribe.pipeline_state, "__file__", str(changed))
        case "namespace":
            monkeypatch.setitem(
                tests.formal.helpers.pipeline_replay_files.FILE_INDEX,
                "run_state.json",
                0,
            )
        case "proof":
            monkeypatch.setattr(binding, "proof_current", lambda: False)
        case "source":
            source = pathlib.Path(peri_scribe.sources.fetching.__file__)
            changed = tmp_path / "unreviewed.py"
            changed.write_text(
                source.read_text(encoding="utf-8") + "\nUNREVIEWED = True\n",
                encoding="utf-8",
            )
            monkeypatch.setattr(peri_scribe.sources.fetching, "__file__", str(changed))
        case _:
            raise AssertionError(unsupported)
    assert not binding.supported()
    directory = tmp_path / "fallback"
    counts = tests.formal.helpers.feed_components.replay(
        {case: {observed}},
        {(case.kinds, case.full): frozenset({receipt.collection()})},
        directory,
    )
    assert counts == tests.formal.helpers.feed_components.Counts(policies=1, native=1)
    assert (directory / "0" / "data" / "2026" / "run_state.json").is_file()
    assert not (directory / "policy").exists()


@pytest.mark.parametrize("prior", [False, True])
def test_policy_delegate_rejects_collection_before_exact_recovery_intent(
    *,
    prior: bool,
    native_collection: tuple[
        tests.formal.helpers.feed_coordinator.Case,
        tests.formal.helpers.feed_components.Receipt,
        tests.formal.helpers.feed_coordinator.Outcome,
    ],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def collect_before_marking(
        year_directory: pathlib.Path,
        *,
        full_fetch_interval: datetime.timedelta | None,
        unconditional: bool,
        collect: peri_scribe.sources.fetch_control.SourceCollector,
        refresh: collections.abc.Callable[[pathlib.Path], bool],
    ) -> bool:
        """Expose a deliberate ordering defect before any recovery requirement exists.

        Returns:
            A result only if the delegation guard failed to reject the defect.
        """
        collect(year_directory, full_fetch_interval=full_fetch_interval)
        return unconditional or refresh(year_directory)

    _, receipt, _ = native_collection
    monkeypatch.setattr(
        peri_scribe.sources.fetch_control,
        "run_ungated_fetch",
        collect_before_marking,
    )
    probe = tests.formal.helpers.feed_components.PolicyProbe(
        case=tests.formal.helpers.feed_coordinator.Case(
            kinds=receipt.kinds,
            full=receipt.full,
            prior=prior,
            index_failure=False,
            deferred=False,
        ),
        directory=tmp_path / "data" / "2026",
        receipt=receipt,
    )
    with pytest.raises(AssertionError, match="exact recovery intent"):
        probe.run()
