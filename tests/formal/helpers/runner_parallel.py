"""Hold proof tools at explicit boundaries without depending on elapsed time."""

import asyncio
import dataclasses
import pathlib

import tests.formal.check
import tests.formal.helpers.process


def metadata_directory(command: list[str]) -> pathlib.Path:
    """Require private storage to exist before a proof process could write to it.

    Args:
        command: The runner's actual tool arguments.

    Returns:
        The existing directory supplied to TLC.
    """
    directory = pathlib.Path(command[command.index("-metadir") + 1])
    assert directory.is_dir()
    return directory


def java_directory(command: list[str]) -> pathlib.Path:
    """Require bundled modules to stay outside Java's shared temporary storage.

    Args:
        command: The runner's actual tool arguments.

    Returns:
        The existing private directory supplied to the JVM.
    """
    options = [value for value in command if value.startswith("-Djava.io.tmpdir=")]
    assert len(options) == 1
    assert command.index(options[0]) < command.index("tlc2.TLC")
    directory = pathlib.Path(options[0].split("=", 1)[1])
    assert directory.is_absolute()
    assert directory.is_dir()
    return directory


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExecutionProbe:
    """Record active tools and private storage while controlling their completion."""

    outcomes: dict[str, Exception | None] = dataclasses.field(default_factory=dict)
    release: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    started: asyncio.Queue[str] = dataclasses.field(default_factory=asyncio.Queue)
    active: set[str] = dataclasses.field(default_factory=set)
    cancelled: set[str] = dataclasses.field(default_factory=set)
    directories: dict[str, pathlib.Path] = dataclasses.field(default_factory=dict)
    java_directories: dict[str, pathlib.Path] = dataclasses.field(default_factory=dict)

    async def execute(
        self,
        command: list[str],
        *,
        standard_input: str,
        cwd: pathlib.Path | None,
        maximum_seconds: float,
    ) -> tests.formal.helpers.process.Result:
        """Keep each fake tool active until an explicit release or cancellation.

        Args:
            command: The runner's actual tool arguments.
            standard_input: Input delivered to the tool.
            cwd: The model source directory.
            maximum_seconds: The admitted tool's execution budget.

        Returns:
            A complete success or deliberately unsuccessful checker result.

        Raises:
            asyncio.CancelledError: If the owning matrix is interrupted.
        """
        assert not standard_input
        assert cwd == tests.formal.check.DIRECTORY
        assert maximum_seconds > 0
        name = pathlib.Path(command[command.index("-config") + 1]).stem
        directory = metadata_directory(command)
        java = java_directory(command)
        assert directory not in self.directories.values()
        assert java not in self.java_directories.values()
        self.directories[name] = directory
        self.java_directories[name] = java
        self.active.add(name)
        self.started.put_nowait(name)
        try:
            await self.release.wait()
            if (failure := self.outcomes.get(name)) is not None:
                raise failure
            return tests.formal.helpers.process.Result(
                returncode=1 if name in self.outcomes else 0,
                stdout="Model checking completed. No error has been found.",
                stderr="",
            )
        except asyncio.CancelledError:
            self.cancelled.add(name)
            raise
        finally:
            self.active.remove(name)


def models() -> tuple[tests.formal.check.Model, ...]:
    """Include queued models so a complete first wave cannot hide skipped checks.

    Returns:
        Seven distinct configurations sharing one model module.
    """
    return tuple(
        tests.formal.check.Model(
            name=f"model-{index}",
            module="Example",
            config=f"model-{index}",
        )
        for index in range(7)
    )


async def held_run(probe: ExecutionProbe) -> tuple[bool, frozenset[str]]:
    """Observe admission while every active tool is blocked on the same event.

    Args:
        probe: Controlled subprocess boundary with observable resource ownership.

    Returns:
        The aggregate result and the tools admitted before any could finish.
    """
    async with asyncio.TaskGroup() as group:
        task = group.create_task(
            tests.formal.check.run_models(
                models(),
                "java",
                pathlib.Path("tools.jar"),
                parallelism=4,
            ),
        )
        for _ in range(4):
            await probe.started.get()
        await asyncio.sleep(0)
        held = frozenset(probe.active)
        probe.release.set()
    return task.result(), held


async def cancelled_run(probe: ExecutionProbe) -> None:
    """Interrupt a full first wave while other models still wait for admission.

    Args:
        probe: Controlled subprocess boundary used to record cancellation delivery.
    """
    async with asyncio.TaskGroup() as group:
        task = group.create_task(
            tests.formal.check.run_models(
                models(),
                "java",
                pathlib.Path("tools.jar"),
                parallelism=4,
            ),
        )
        for _ in range(4):
            await probe.started.get()
        await asyncio.sleep(0)
        task.cancel()
        await task
