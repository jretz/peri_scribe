"""Run the integrated ordinary pytest phase in native file-owned lanes."""

from __future__ import annotations

import asyncio
import collections
import collections.abc
import contextlib
import dataclasses
import hashlib
import importlib.metadata
import json
import math
import os
import pathlib
import shlex
import signal
import sys
import types

import coverage
import pytest

import tests.formal.helpers.process
import tests.helpers.ordinary_receipts


ROOT = pathlib.Path.cwd()
MODULE = __spec__.name if __spec__ is not None else pathlib.Path(__file__).stem
WORK = "PERI_SCRIBE_ORDINARY_LANE_DIRECTORY"
INDEX = "PERI_SCRIBE_ORDINARY_LANE_INDEX"
DIGEST = "PERI_SCRIBE_ORDINARY_PLAN_DIGEST"
IGNORED = {".cache", ".git", ".lake", ".pytest_cache", "__pycache__"}
PLUGINS = {
    "platformdirs.pytest_plugin",
    "_hypothesis_pytestplugin",
    "pytest_cov.plugin",
    "xdist.plugin",
    "xdist.looponfail",
    "pytest_asyncio.plugin",
    "pytest_slow_first",
    "pytest_tqdm.plugin",
    "time_machine",
    "anyio.pytest_plugin",
    "requests_mock.contrib._pytest_plugin",
}
ENABLE = "PERI_SCRIBE_ORDINARY_LANES"
LANE_COUNT = 4

type Generation = tuple[int, int, int, int, int, int]
type Collected = tuple[str, ...]


class UnsupportedConfigurationError(Exception):
    """The native lane plan supports only the standard integrated pytest command."""


class LaneError(Exception):
    """The current lane session cannot supply complete passing evidence."""


@dataclasses.dataclass(kw_only=True)
class Lane:
    """Own only the selected files and receipt state for one native pytest run."""

    directory: pathlib.Path
    index: int
    digest: str
    files: types.MappingProxyType[str, int]
    directories: frozenset[str]
    completed: list[str] = dataclasses.field(default_factory=list)


LANE = pytest.StashKey[Lane]()


def encoded(value: object) -> bytes:
    """Use one stable representation for current receipts and plan identity.

    Returns:
        The serialized representation.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def publish(path: pathlib.Path, value: object) -> None:
    """Expose a complete receipt only after the producer closes its staging file."""
    staging = path.with_suffix(".tmp")
    with staging.open("xb") as stream:
        stream.write(encoded(value))
    staging.replace(path)


def generation(path: pathlib.Path) -> Generation:
    """Bind native selection to file generations while ignoring read-triggered atime.

    Returns:
        The identity of the current file generation.
    """
    status = path.stat()
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def input_paths() -> tuple[dict[str, Generation], frozenset[str]]:
    """Discover current paths, including shared fixtures outside ordinary collection.

    Returns:
        Input file generations and the ordinary collection candidates.

    Raises:
        UnsupportedConfigurationError: If a collection path needs standard pytest.
    """
    inputs = {"pyproject.toml": generation(ROOT / "pyproject.toml")}
    candidates = set()
    for root in ("src", "tests"):
        for parent, children, files in os.walk(ROOT / root):
            directory = pathlib.Path(parent)
            children[:] = [name for name in children if name not in IGNORED]
            if any((directory / name).is_symlink() for name in children):
                message = "Symlinked collection directories use stock pytest"
                raise UnsupportedConfigurationError(message)
            for name in files:
                path = directory / name
                relative = path.relative_to(ROOT)
                if path.is_symlink():
                    message = "Symlinked collection files use stock pytest"
                    raise UnsupportedConfigurationError(message)
                if name == ".DS_Store":
                    continue
                key = relative.as_posix()
                inputs[key] = generation(path)
                if relative.is_relative_to("tests/formal"):
                    continue
                if name == "conftest.py" and key != "tests/conftest.py":
                    message = "Nested collection plugins use stock pytest"
                    raise UnsupportedConfigurationError(message)
                candidates.add(key)
    return inputs, frozenset(candidates)


def qualify(directory: pathlib.Path, count: int) -> None:
    """Keep explicit selection and unknown plugin behavior on stock pytest.

    Raises:
        UnsupportedConfigurationError: If the invocation differs from the default.
    """
    if count != LANE_COUNT:
        message = "Native pytest worker count falls outside the integrated budget"
        raise UnsupportedConfigurationError(message)
    arguments = shlex.split(os.environ.get("PYTEST_ADDOPTS", ""))
    accepted: set[tuple[str, ...]] = {(), ("-n", str(count))}
    base = f"--basetemp={directory / 'pytest-temp'}"
    accepted |= {(*variant, base) for variant in tuple(accepted)}
    if tuple(arguments) not in accepted or any(
        os.environ.get(name)
        for name in (
            "PYTEST_PLUGINS",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
            "COVERAGE_PROCESS_START",
        )
    ):
        message = "Custom pytest configuration uses stock pytest"
        raise UnsupportedConfigurationError(message)
    plugins = importlib.metadata.entry_points(group="pytest11")
    if {plugin.value for plugin in plugins} != PLUGINS:
        message = "A different pytest plugin inventory uses stock pytest"
        raise UnsupportedConfigurationError(message)


def history(path: pathlib.Path) -> list[dict[str, object]]:
    """Read previous timing hints without making them authoritative for membership.

    Returns:
        Recorded timing hints, or an empty list for a first run.

    Raises:
        UnsupportedConfigurationError: If the timing format changed.
    """
    try:
        data = json.loads(path.read_bytes())
    except FileNotFoundError:
        return []
    if data["format_version"] != "1.0.0":
        message = "Unrecognized pytest timing history uses stock pytest"
        raise UnsupportedConfigurationError(message)
    return data["tests"]


def file_for(nodeid: str) -> str:
    """Map a native node identity to its root-relative collection file.

    Returns:
        The file part of the node ID.
    """
    return nodeid.partition("::")[0]


def assign(
    candidates: frozenset[str],
    rows: list[dict[str, object]],
    count: int,
) -> dict[str, int]:
    """Balance current whole files using prior native durations only as weights.

    Returns:
        The single owning lane for every candidate path.
    """
    weights: dict[str, float] = collections.defaultdict(float)
    for row in rows:
        weight = sum(
            value
            for key, value in row.items()
            if key.endswith("_duration")
            and isinstance(value, int | float)
            and math.isfinite(value)
            and value >= 0
        )
        weights[file_for(str(row["nodeid"]))] += weight
    for name in candidates:
        if not weights[name] and name.endswith(".py"):
            weights[name] = (ROOT / name).stat().st_size / 100_000
    totals = [0.0] * count
    owners = {}
    for name in sorted(candidates, key=lambda path: (-weights[path], path)):
        owner = min(range(count), key=totals.__getitem__)
        owners[name] = owner
        totals[owner] += weights[name] + 0.002
    return owners


def pytest_configure(config: pytest.Config) -> None:
    """Accept only the immutable current plan published by the ordinary runner.

    Raises:
        pytest.UsageError: If the plan identity or default collection roots changed.
    """
    if WORK not in os.environ:
        return
    root = pathlib.Path(os.environ[WORK])
    index = int(os.environ[INDEX])
    digest = os.environ[DIGEST]
    contents = (root / "plan.json").read_bytes()
    if hashlib.sha256(contents).hexdigest() != digest or config.rootpath != ROOT:
        message = "Native pytest ownership plan or root changed"
        raise pytest.UsageError(message)
    if config.args != ["src", "tests"] or config.getini("testpaths") != [
        "src",
        "tests",
    ]:
        message = "Native pytest requires the ordinary default roots"
        raise pytest.UsageError(message)
    owners = json.loads(contents)["owners"]
    config.stash[LANE] = Lane(
        directory=root / f"lane-{index}",
        index=index,
        digest=digest,
        files=types.MappingProxyType(owners),
        directories=frozenset(
            parent.as_posix()
            for name, owner in owners.items()
            if owner == index
            for parent in pathlib.PurePosixPath(name).parents
        ),
    )


@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(
    collection_path: pathlib.Path,
    config: pytest.Config,
) -> bool | None:
    """Skip other owners while retaining native collectors for every owned path.

    Returns:
        True to defer to a different lane, or None for native collection.
    """
    lane = config.stash[LANE]
    name = collection_path.relative_to(ROOT).as_posix()
    if collection_path.is_dir():
        return True if name not in lane.directories else None
    return True if lane.files.get(name) != lane.index else None


@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session: pytest.Session) -> None:
    """Record the actual ordered collection after all native selection hooks.

    Raises:
        pytest.UsageError: If a collected node is duplicated or assigned elsewhere.
    """
    lane = session.config.stash[LANE]
    nodeids = tuple(item.nodeid for item in session.items)
    if len(set(nodeids)) != len(nodeids) or any(
        lane.files.get(file_for(nodeid)) != lane.index for nodeid in nodeids
    ):
        message = "A native pytest node is duplicated or outside its lane"
        raise pytest.UsageError(message)
    publish(lane.directory / "collected.json", (lane.digest, lane.index, nodeids))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(
    item: pytest.Item,
) -> collections.abc.Generator[None, bool | None, bool | None]:
    """Observe completion of the native fixture, test, and teardown protocol.

    Returns:
        The native pytest protocol's result.
    """
    result = yield
    item.config.stash[LANE].completed.append(item.nodeid)
    return result


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(
    session: pytest.Session,
) -> collections.abc.Generator[None]:
    """Publish completion only after pytest and its native coverage hooks succeed."""
    yield
    if session.exitstatus == 0:
        lane = session.config.stash[LANE]
        publish(
            lane.directory / "completed.json",
            (lane.digest, lane.index, lane.completed),
        )


async def stop(launch: asyncio.Task[asyncio.subprocess.Process]) -> None:
    """Reap one direct lane even when cancellation raced with its launch."""
    (child,) = await asyncio.gather(launch, return_exceptions=True)
    if isinstance(child, BaseException) or child.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        child.send_signal(signal.SIGINT)
    try:
        await asyncio.wait_for(child.wait(), 3)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            child.kill()
        await child.wait()


async def run_lane(
    directory: pathlib.Path,
    index: int,
    digest: str,
    rows: list[dict[str, object]],
) -> None:
    """Run unmodified native pytest under the enclosing ordinary process group.

    Raises:
        LaneError: If the native pytest process fails.
    """
    lane = directory / f"lane-{index}"
    lane.mkdir()
    slow = lane / "slow.json"
    publish(slow, {"format_version": "1.0.0", "tests": rows})
    environment = os.environ | {
        WORK: str(directory),
        INDEX: str(index),
        DIGEST: digest,
        "COVERAGE_FILE": str(lane / "coverage"),
        "SLOW_FIRST_PATH": str(slow),
    }
    environment.pop("PYTEST_ADDOPTS", None)
    command = (
        sys.executable,
        "-m",
        "pytest",
        "-c",
        "pyproject.toml",
        "-n0",
        "-p",
        MODULE,
        "-o",
        f"cache_dir={lane / 'cache'}",
        "--basetemp",
        str(directory.parent / "pytest-temp" / f"lane-{index}"),
        f"--junitxml={lane / 'results.xml'}",
    )
    with (lane / "pytest.log").open("xb") as output:
        launch = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *command,
                cwd=ROOT,
                env=environment,
                stdout=output,
                stderr=output,
            ),
        )
        try:
            child = await asyncio.shield(launch)
            status = await child.wait()
        except BaseException:
            await tests.formal.helpers.process.finish(asyncio.create_task(stop(launch)))
            raise
    if status:
        log = lane / "pytest.log"
        print(
            "\n".join(log.read_text(errors="replace").splitlines()[-60:]),
            file=sys.stderr,
        )
        message = f"Native pytest lane {index} exited {status}. See {log}"
        raise LaneError(message)


def read_receipt(path: pathlib.Path, digest: str, index: int) -> Collected:
    """Reject evidence not owned by this invocation and exact lane.

    The shared decoder uses LaneError for an incompatible plan or lane.

    Returns:
        The ordered native node IDs in the receipt.
    """
    return tests.helpers.ordinary_receipts.read_receipt(
        path,
        digest,
        index,
        error_type=LaneError,
    )


def collected(
    directory: pathlib.Path,
    digest: str,
    owners: dict[str, int],
    count: int,
) -> Collected:
    """Validate disjoint native node identities against the current file ownership map.

    Returns:
        The complete, sorted collection for the current invocation.

    Raises:
        LaneError: If any collected node is duplicated or assigned elsewhere.
    """
    seen: set[str] = set()
    for index in range(count):
        lane = directory / f"lane-{index}"
        nodes = read_receipt(lane / "collected.json", digest, index)
        if (
            len(set(nodes)) != len(nodes)
            or seen.intersection(nodes)
            or any(owners.get(file_for(nodeid)) != index for nodeid in nodes)
        ):
            message = f"Duplicated or unowned native pytest items in {lane}"
            raise LaneError(message)
        seen.update(nodes)
    return tuple(sorted(seen))


def finish_coverage(
    directory: pathlib.Path,
    target: pathlib.Path,
    digest: str,
    count: int,
) -> None:
    """Publish the union of current native branches for the existing coverage gate.

    Raises:
        LaneError: If any lane has incomplete or invalid coverage evidence.
    """
    staging = directory / "combined-coverage"
    merged = coverage.CoverageData(basename=str(staging))
    for index in range(count):
        lane = directory / f"lane-{index}"
        if (
            read_receipt(lane / "collected.json", digest, index)
            != read_receipt(
                lane / "completed.json",
                digest,
                index,
            )
            or not (lane / "results.xml").is_file()
        ):
            message = f"Incomplete native pytest protocol evidence in {lane}"
            raise LaneError(message)
        database = lane / "coverage"
        if not database.is_file():
            message = f"Missing native coverage data in {lane}"
            raise LaneError(message)
        current = coverage.CoverageData(basename=str(database))
        current.read()
        files = current.measured_files()
        if (
            not current.has_arcs()
            or not files
            or any(
                not pathlib.PurePosixPath(name).is_relative_to("src") for name in files
            )
        ):
            message = f"Unexpected ordinary source coverage in {lane}"
            raise LaneError(message)
        merged.update(current)
    merged.write()
    if target.exists():
        message = f"Coverage session already contains {target.name}"
        raise LaneError(message)
    target.hardlink_to(staging)
    staging.unlink()


async def run_lanes(
    work: pathlib.Path,
    digest: str,
    lane_rows: list[list[dict[str, object]]],
) -> None:
    """Stop the remaining workers if a lane fails or the run is cancelled."""
    async with asyncio.TaskGroup() as group:
        for index, lane_history in enumerate(lane_rows):
            group.create_task(run_lane(work, index, digest, lane_history))


def coverage_session() -> tuple[pathlib.Path, bytes, str]:
    """Find the fresh coverage session owned by the integrated command.

    Returns:
        The session directory, exact marker bytes, and run identity.

    Raises:
        UnsupportedConfigurationError: If the invocation lacks a coverage session.
        LaneError: If that session already holds ordinary test evidence.
    """
    try:
        directory = pathlib.Path(os.environ["PERI_SCRIBE_COVERAGE_DIRECTORY"]).resolve(
            strict=True,
        )
        target = pathlib.Path(os.environ["COVERAGE_FILE"])
        session_bytes = (directory / "session.json").read_bytes()
        identity = json.loads(session_bytes)
    except (KeyError, FileNotFoundError, ValueError) as error:
        message = "Native pytest requires a coverage session"
        raise UnsupportedConfigurationError(message) from error
    if (
        target != directory / "python-data"
        or identity.get("version") != 1
        or identity.get("directory") != str(directory)
        or not identity.get("runId")
    ):
        message = "Native pytest requires an ordinary coverage session"
        raise UnsupportedConfigurationError(message)
    if target.exists() or (directory / "pytest-lanes").exists():
        message = "The ordinary coverage session already has Python evidence"
        raise LaneError(message)
    return directory, session_bytes, identity["runId"]


def save_timings(work: pathlib.Path, timing_path: pathlib.Path, count: int) -> None:
    """Carry forward timing hints once all lanes and coverage have passed."""
    try:
        measured = [
            row
            for index in range(count)
            for row in history(work / f"lane-{index}" / "slow.json")
        ]
        publish(timing_path, {"format_version": "1.0.0", "tests": measured})
    except (UnsupportedConfigurationError, OSError, ValueError) as error:
        print(f"Could not save pytest lane timings. {error}", file=sys.stderr)


def run(count: int) -> None:
    """Publish fresh ordinary branch evidence from the current owned lanes.

    Raises:
        LaneError: If the current lane session has incomplete evidence.
    """
    directory, session_bytes, run_id = coverage_session()
    qualify(directory, count)
    inputs, candidates = input_paths()
    timing_path = pathlib.Path(
        os.environ.get("SLOW_FIRST_PATH", "pytest-slow-first.json"),
    )
    rows = history(timing_path)
    owners = assign(candidates, rows, count)
    lane_rows: list[list[dict[str, object]]] = [[] for _ in range(count)]
    for row in rows:
        if (owner := owners.get(file_for(str(row["nodeid"])))) is not None:
            lane_rows[owner].append(row)

    work = directory / "pytest-lanes"
    work.mkdir()
    (directory / "pytest-temp").mkdir()
    plan = work / "plan.json"
    publish(plan, {"session": run_id, "inputs": inputs, "owners": owners})
    plan.chmod(0o400)
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    asyncio.run(run_lanes(work, digest, lane_rows))
    nodeids = collected(work, digest, owners, count)
    message = "Native pytest plan inputs changed during the session"
    try:
        unchanged = input_paths() == (inputs, candidates)
    except (UnsupportedConfigurationError, OSError) as error:
        raise LaneError(message) from error
    if (
        not unchanged
        or (directory / "session.json").read_bytes() != session_bytes
        or hashlib.sha256(plan.read_bytes()).hexdigest() != digest
    ):
        raise LaneError(message)
    finish_coverage(work, directory / "python-data", digest, count)
    save_timings(work, timing_path, count)
    print(f"{len(nodeids)} native pytest items completed in {count} lanes", flush=True)


def main() -> int:
    """Select native lanes for a qualified integrated invocation.

    Returns:
        The ordinary pytest exit status.
    """
    if os.environ.get(ENABLE) != "1" or sys.argv[1:]:
        return int(pytest.main())
    try:
        count = int(os.environ.get("PERI_SCRIBE_TEST_WORKERS", str(LANE_COUNT)))
    except ValueError:
        return int(pytest.main())
    try:
        run(count)
    except UnsupportedConfigurationError as error:
        print(error, file=sys.stderr, flush=True)
        return int(pytest.main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
