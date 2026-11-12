"""Qualify the collection cut and marker implementation before sharing witnesses."""

import ast
import asyncio
import datetime
import functools
import hashlib
import itertools
import json
import pathlib
import types

import peri_scribe.concurrency
import peri_scribe.pipeline_state
import peri_scribe.sources.fetching
import peri_scribe.sources.full_fetch_state
import tests.formal.helpers.feed_coordinator
import tests.formal.helpers.oracle
import tests.formal.helpers.pipeline_effect_matrix
import tests.formal.helpers.pipeline_file_footprint
import tests.formal.helpers.pipeline_ordered_binding
import tests.formal.helpers.pipeline_replay_files


# Changes to these closed implementations require a new component-boundary review.
EXPECTED_CAPACITY = 2
SOURCES = (
    (
        peri_scribe.sources.fetching,
        "77776eb6aa417825af8858b6e967c64e8afc691fa9f798c6bd409ee981ca304a",
        (
            "collect_feed_outcomes",
            "collect_feeds",
            "collect_one_feed",
        ),
    ),
    (
        peri_scribe.concurrency,
        "35807fbcb542e53c37fae944d1316875aee1170d9fbd53e2842c08f646f3f905",
        ("run_blocking", "finish_worker"),
    ),
    (
        peri_scribe.pipeline_state,
        "61a0cec5e5d4f86648ee97762a535f33312fc1a819a42b8fa42ba7acbf1159ec",
        (
            "read_state",
            "state_path",
            "deferred_inputs_path",
            "has_deferred_inputs",
        ),
    ),
    (
        peri_scribe.sources.full_fetch_state,
        "b5ed8944fabd978bc12927e070dcecfd688c347da8fcd7846df3043f0e5ea55e",
        (
            "state_path",
            "read_state",
            "write_state",
            "parsed_timestamp",
            "utc_timestamp_text",
            "malformed_state_error",
            "full_fetch_is_due",
        ),
    ),
    (
        tests.formal.helpers.feed_coordinator,
        "5e89839d1bee35ba0f9dc30bbac4495cf8f8b87b7aa94533e492fc095df88a96",
        (
            "CollectionProbe.fetch",
            "CollectionProbe.index",
            "CollectionProbe.install",
            "CollectionProbe.prepare",
            "CollectionProbe.check_collection",
            "CollectionProbe.pending",
            "CollectionProbe.acknowledged",
            "CollectionProbe.run",
        ),
    ),
    (
        tests.formal.helpers.pipeline_replay_files,
        "3d86b99ace88be3f11cf763c9729914f04adf3f0577ffc35d2249aefae867268",
        (
            "Memory.at",
            "Memory.mutate",
            "Memory.__post_init__",
            "File.entry",
            "File.read_bytes",
            "File.replace_text",
            "File.exists",
            "File.touch",
            "File.remove",
        ),
    ),
)
LIVE = (
    *(
        binding
        for module, _, _ in SOURCES
        for binding in tests.formal.helpers.pipeline_ordered_binding.reviewed_bindings(
            module,
        )
    ),
    *(
        tests.formal.helpers.pipeline_ordered_binding.live(owner, name)
        for owner, names in (
            (
                asyncio,
                (
                    "run",
                    "TaskGroup",
                    "Semaphore",
                    "create_task",
                    "to_thread",
                    "shield",
                    "gather",
                    "CancelledError",
                ),
            ),
            (functools, ("partial",)),
            (datetime, ("datetime", "UTC")),
            (json, ("loads", "dumps")),
            (pathlib.Path, ("read_text",)),
        )
        for name in names
    ),
)


def reviewed(module: types.ModuleType, digest: str, names: tuple[str, ...]) -> bool:
    """Match both inspected source and loaded executable definitions.

    Returns:
        Whether the complete module and relevant executable entries are unchanged.
    """
    binding = tests.formal.helpers.pipeline_ordered_binding
    footprint = tests.formal.helpers.pipeline_file_footprint
    if not binding.imported(module) or module.__file__ is None:
        return False
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    normalized = footprint.normalize(ast.parse(source))
    if hashlib.sha256(normalized.encode()).hexdigest() != digest:
        return False
    for name, signature in binding.compiled_entries(source, names):
        owner, separator, member = name.partition(".")
        function = (
            getattr(getattr(module, owner), member)
            if separator
            else getattr(module, owner)
        )
        if (
            not isinstance(function, types.FunctionType)
            or function.__globals__ is not vars(module)
            or footprint.signature(function.__code__) != signature
            or function.__defaults__ is not None
            or function.__kwdefaults__
            != ({"stopped": None} if name == "run_blocking" else None)
        ):
            return False
    return True


def proof_current() -> bool:
    """Require a current compiled composition proof before factoring native work.

    Returns:
        Whether the checked proof and executable follow all of their source inputs.
    """
    directory = tests.formal.helpers.oracle.DIRECTORY / "lean"
    try:
        proof = directory / "PeriScribe" / "FetchComposition.lean"
        checked = directory / ".lake/build/lib/lean/PeriScribe/FetchComposition.olean"
        binary = directory / ".lake/build/bin/oracle"
        return (
            tests.formal.helpers.pipeline_file_footprint.current_oracle()
            and binary.stat().st_mtime_ns
            >= checked.stat().st_mtime_ns
            >= proof.stat().st_mtime_ns
        )
    except OSError:
        return False


def supported() -> bool:
    """Fail closed to full native replay when the reviewed component no longer applies.

    Returns:
        Whether the native file proof and the complete live collection closure qualify.
    """
    files = tests.formal.helpers.pipeline_replay_files
    footprint = tests.formal.helpers.pipeline_file_footprint
    matrix = tests.formal.helpers.pipeline_effect_matrix
    try:
        return (
            proof_current()
            and all(binding.valid() for binding in LIVE)
            and all(
                itertools.starmap(reviewed, SOURCES),
            )
            and tests.formal.helpers.feed_coordinator.CAPACITY == EXPECTED_CAPACITY
            and files.FILES == footprint.FRAME_FILES
            and tuple(files.FILE_INDEX.items())
            == tuple(
                (name, number) for number, name in enumerate(footprint.FRAME_FILES)
            )
            and frozenset(footprint.FRAME_FILES[-3:]) == files.MARKERS
            and footprint.resolve(matrix, matrix.FRAME_TYPES) is not None
        )
    except OSError, SyntaxError, UnicodeError, AttributeError, KeyError, TypeError:
        return False
