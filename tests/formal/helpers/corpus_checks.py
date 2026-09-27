"""Exercise shared proof inputs across real cooperating Python processes."""

import asyncio
import dataclasses
import os
import pathlib
import sys
import typing

import pydantic

import tests.formal.helpers.corpus
import tests.formal.helpers.process


@dataclasses.dataclass(frozen=True, kw_only=True)
class Sample:
    """Retain a typed value and its producer across publication and deserialization."""

    producer: str
    values: tuple[int, ...] = (2, 3, 5)


ADAPTER = pydantic.TypeAdapter(Sample)
INTERRUPTED_EXIT = 29
Behavior = typing.Literal["success", "held", "raise", "exit"]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Producer:
    """Record every attempted build independently of its private staging lifetime."""

    attempts: pathlib.Path
    behavior: Behavior = "success"

    def build(self, directory: pathlib.Path) -> Sample:
        """Leave incomplete input behind before the selected completion boundary.

        Args:
            directory: Storage private to this build attempt.

        Returns:
            A complete typed sample, only when construction succeeds.

        Raises:
            ValueError: When the attempted corpus generation fails.
        """
        with self.attempts.open("a") as stream:
            stream.write(f"{directory}\n")
        (directory / "partial-input").write_text("incomplete")
        if self.behavior == "raise":
            message = "corpus generation failed"
            raise ValueError(message)
        if self.behavior == "exit":
            os._exit(INTERRUPTED_EXIT)
        if self.behavior == "held":
            print("building", flush=True)
            assert sys.stdin.readline().strip() == "release"
        return Sample(producer=self.behavior)


def command(
    directory: pathlib.Path,
    attempts: pathlib.Path,
    behavior: Behavior,
) -> list[str]:
    """Keep each requester in a fresh interpreter with no inherited cache state.

    Args:
        directory: Session storage shared by the participating processes.
        attempts: Independently retained record of builder calls.
        behavior: Boundary exercised if this requester becomes the builder.

    Returns:
        The direct subprocess arguments.
    """
    return [
        sys.executable,
        "-m",
        "tests.formal.helpers.corpus_checks",
        str(directory),
        str(attempts),
        behavior,
    ]


async def request(
    directory: pathlib.Path,
    attempts: pathlib.Path,
    behavior: Behavior,
    processes: list[asyncio.subprocess.Process],
) -> asyncio.subprocess.Process:
    """Expose requester admission before it can acquire the shared corpus lock.

    Args:
        directory: Session storage shared by cooperating requesters.
        attempts: Independently retained record of builder calls.
        behavior: Boundary exercised if this requester becomes the builder.
        processes: Children requiring cleanup if any bounded check fails.

    Returns:
        A live process that has reached the corpus loader.
    """
    process = await asyncio.create_subprocess_exec(
        *command(directory, attempts, behavior),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    processes.append(process)
    assert process.stdout is not None
    assert await process.stdout.readline() == b"loading\n"
    return process


async def concurrent(
    directory: pathlib.Path,
    attempts: pathlib.Path,
) -> tuple[tests.formal.helpers.process.Result, ...]:
    """Keep the producer incomplete while independent readers request its result.

    Args:
        directory: Session storage shared by the participating processes.
        attempts: Independently retained record of builder calls.

    Returns:
        Each process's final outcome after the initial producer is released.
    """
    processes: list[asyncio.subprocess.Process] = []
    try:
        first = await request(directory, attempts, "held", processes)
        assert first.stdout is not None
        assert await first.stdout.readline() == b"building\n"
        for _ in range(2):
            await request(directory, attempts, "success", processes)
        assert first.stdin is not None
        first.stdin.write(b"release\n")
        await first.stdin.drain()
        outputs = await asyncio.gather(
            *(process.communicate() for process in processes),
        )
        results = []
        for process, (stdout, stderr) in zip(processes, outputs, strict=True):
            assert process.returncode is not None
            results.append(
                tests.formal.helpers.process.Result(
                    returncode=process.returncode,
                    stdout=stdout.decode(),
                    stderr=stderr.decode(),
                ),
            )
        return tuple(results)
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
        await asyncio.gather(*(process.communicate() for process in processes))


def main() -> None:
    """Allow abrupt producer termination without terminating the pytest worker."""
    directory, attempts, raw_behavior = sys.argv[1:]
    behavior = pydantic.TypeAdapter(Behavior).validate_python(raw_behavior)
    print("loading", flush=True)
    value = tests.formal.helpers.corpus.load(
        pathlib.Path(directory),
        "sample",
        ADAPTER,
        Producer(attempts=pathlib.Path(attempts), behavior=behavior).build,
    )
    print(ADAPTER.dump_json(value).decode(), flush=True)


if __name__ == "__main__":
    main()
