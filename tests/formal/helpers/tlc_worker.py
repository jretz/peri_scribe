"""Run independent TLC requests inside an owned JVM process group.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

import asyncio
import base64
import contextlib
import dataclasses
import hashlib
import os
import pathlib
import re
import struct
import sys
import tempfile
import typing

import tests.formal.helpers.process


SOURCE = pathlib.Path(__file__).resolve().parents[1] / "tla" / "TlcWorker.java"
FRAME_SOURCE = SOURCE.with_name("FrameChecker.java")
FRAME_ARCHIVE = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
FRAME_REQUEST = "--peri-scribe-frame"
FRAME_UNSUPPORTED = 125
JAVA_OPTIONS = (
    "-XX:ActiveProcessorCount=1",
    "-XX:+UseSerialGC",
    "-Xmx1g",
    # Fresh request classes make repeated optimizing compilation expensive.
    "-XX:TieredStopAtLevel=1",
)
MAXIMUM_REQUEST_BYTES = 65536
MAXIMUM_RESPONSE_BYTES = 128
MAXIMUM_DIAGNOSTIC_BYTES = 8192
MAXIMUM_EXIT_STATUS = 255
CLOSE_SECONDS = 5
RESPONSE = re.compile(rb"(\d+) (\d+)\n")
OUTPUT = "stdout.log"
ERRORS = "stderr.log"


def require_outer_group() -> None:
    """Keep every reusable worker independently cancellable.

    Raises:
        OSError: If an outer proof job already owns this process group.
    """
    if tests.formal.helpers.process.inherited_group() is not None:
        message = "TLC workers require an independent proof process group"
        raise OSError(message)


def supports_frames(jar: pathlib.Path) -> bool:
    """Qualify the archive whose resolved TLC operators the frame checker uses.

    Returns:
        Whether the archive is the reviewed TLC binary.
    """
    with jar.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == FRAME_ARCHIVE


async def compile_worker(
    java: str,
    directory: pathlib.Path,
    *,
    jar: pathlib.Path | None = None,
) -> pathlib.Path:
    """Compile the transport with the same toolchain as its future workers.

    Args:
        java: The selected Java executable.
        directory: The current proof invocation's temporary storage.
        jar: The archive eligible for the optional frame checker.

    Returns:
        The directory containing the compiled worker classes.

    Raises:
        OSError: If this proof job cannot own the compiler or compilation fails.
    """
    require_outer_group()
    directory = await asyncio.to_thread(directory.resolve)
    classes = pathlib.Path(tempfile.mkdtemp(prefix="tlc-worker-", dir=directory))
    framed = jar is not None and await asyncio.to_thread(supports_frames, jar)
    result = await tests.formal.helpers.process.execute(
        [
            str(pathlib.Path(java).with_name("javac")),
            "-J-XX:ActiveProcessorCount=1",
            "-J-XX:+UseSerialGC",
            "-J-Xmx256m",
            "-encoding",
            "UTF-8",
            "-d",
            str(classes),
            *(["-classpath", str(jar), str(FRAME_SOURCE)] if framed else []),
            str(SOURCE),
        ],
        standard_input="",
        cwd=None,
        maximum_seconds=60,
        can_start_nested_tools=False,
    )
    if result.returncode or not await asyncio.to_thread(
        (classes / "TlcWorker.class").is_file,
    ):
        message = f"TLC worker compilation failed\n{result.stdout}{result.stderr}"
        raise OSError(message)
    return classes


def request_line(identifier: int, arguments: list[str]) -> bytes:
    """Preserve UTF-8 argument boundaries through the line transport.

    Args:
        identifier: The current worker request's sequence number.
        arguments: Private JVM directory followed by TLC arguments.

    Returns:
        The complete bounded wire request.

    Raises:
        ValueError: If the request exceeds the wire size limit.
    """
    payload = bytearray()
    for argument in arguments:
        value = argument.encode()
        if len(payload) + len(value) + 4 > MAXIMUM_REQUEST_BYTES:
            message = "TLC worker request exceeds its size limit"
            raise ValueError(message)
        payload.extend(struct.pack("!I", len(value)))
        payload.extend(value)
    line = f"{identifier} ".encode() + base64.b64encode(payload) + b"\n"
    if len(line) > MAXIMUM_REQUEST_BYTES:
        message = "TLC worker request exceeds its size limit"
        raise ValueError(message)
    return line


@dataclasses.dataclass(frozen=True, kw_only=True)
class Connection:
    """Keep launch ownership together with diagnostics outside the reply pipe."""

    launch: asyncio.Task[asyncio.subprocess.Process]
    diagnostics: typing.BinaryIO
    resources: contextlib.ExitStack


def diagnostic_excerpt(connection: Connection) -> str:
    """Preserve transport diagnostics without changing the child's file offset.

    Args:
        connection: The failed worker's independent diagnostic stream.

    Returns:
        A bounded excerpt of the JVM or launcher error output.
    """
    with contextlib.suppress(OSError):
        return os.pread(
            connection.diagnostics.fileno(),
            MAXIMUM_DIAGNOSTIC_BYTES,
            0,
        ).decode(errors="replace")
    return ""


async def exit_after_eof(connection: Connection) -> None:
    """Allow a finished JVM to exit and its launcher to reap it normally.

    Args:
        connection: The idle worker whose request stream has finished.

    Raises:
        OSError: If the worker emits more replies or exits unsuccessfully.
    """
    worker = await asyncio.shield(connection.launch)
    assert worker.stdin is not None
    assert worker.stdout is not None
    worker.stdin.close()
    if await worker.stdout.read(1):
        message = "TLC worker emitted an unexpected reply at shutdown"
        raise OSError(message)
    status = await worker.wait()
    if status:
        message = f"TLC worker exited with status {status} at shutdown"
        raise OSError(message)
    tests.formal.helpers.process.kill_group(worker.pid)


async def exchange(
    connection: Connection,
    identifier: int,
    line: bytes,
    java_directory: pathlib.Path,
) -> tests.formal.helpers.process.Result:
    """Require the current request's complete receipt before reading its output.

    Args:
        connection: The worker's protected launch and transport.
        identifier: The one request outstanding on that transport.
        line: The complete encoded request.
        java_directory: Private stdout and stderr storage for this request.

    Returns:
        The identified exit status and full diagnostic files.

    Raises:
        OSError: If the worker replies with an invalid result.
    """
    worker = await asyncio.shield(connection.launch)
    assert worker.stdin is not None
    assert worker.stdout is not None
    worker.stdin.write(line)
    await worker.stdin.drain()
    reply = await worker.stdout.readline()
    status = RESPONSE.fullmatch(reply)
    if (
        status is None
        or int(status[1]) != identifier
        or int(status[2]) > MAXIMUM_EXIT_STATUS
    ):
        message = f"Unexpected TLC reply for request {identifier}"
        raise OSError(message)
    stdout = await asyncio.to_thread((java_directory / OUTPUT).read_bytes)
    stderr = await asyncio.to_thread((java_directory / ERRORS).read_bytes)
    return tests.formal.helpers.process.Result(
        returncode=int(status[2]),
        stdout=stdout.decode(),
        stderr=stderr.decode(),
    )


class Worker:
    """Give each request exclusive use of a reusable, independently owned JVM."""

    def __init__(
        self,
        java: str,
        jar: pathlib.Path,
        classes: pathlib.Path,
        cwd: pathlib.Path,
    ) -> None:
        """Capture the toolchain and files shared across fresh TLC classloaders.

        Args:
            java: The selected Java executable.
            jar: The pinned TLC tools archive.
            classes: The compiled worker class directory.
            cwd: The specifications' working directory.
        """
        require_outer_group()
        self.command = [
            sys.executable,
            str(tests.formal.helpers.process.LAUNCHER),
            java,
            *JAVA_OPTIONS,
            "-cp",
            str(classes),
            "TlcWorker",
            str(jar.resolve()),
        ]
        self.cwd = cwd
        self.framed = (classes / "FrameChecker.class").is_file()
        self.connection: Connection | None = None
        self.lock = asyncio.Lock()
        self.identifier = 0
        self.closed = False

    def start(self) -> Connection:
        """Retain the launch task so cancellation can still acquire its handle.

        Returns:
            The owned launch and its independent diagnostic stream.
        """
        with contextlib.ExitStack() as resources:
            diagnostics = resources.enter_context(tempfile.TemporaryFile())
            launch = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    *self.command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=diagnostics,
                    cwd=self.cwd,
                    start_new_session=True,
                    limit=MAXIMUM_RESPONSE_BYTES,
                ),
            )
            return Connection(
                launch=launch,
                diagnostics=diagnostics,
                resources=resources.pop_all(),
            )

    async def stop(self) -> None:
        """Reap an owned worker before admitting another request."""
        if (connection := self.connection) is None:
            return
        cleanup = asyncio.create_task(
            tests.formal.helpers.process.terminate(
                connection.launch,
                None,
                interrupt_grace_seconds=0,
            ),
        )
        try:
            await tests.formal.helpers.process.finish(cleanup)
        except BaseException:
            self.closed = True
            raise
        self.release(connection)

    def release(self, connection: Connection) -> None:
        """Close the remaining diagnostics after the owned group is gone.

        Args:
            connection: The completed worker connection.
        """
        connection.resources.close()
        self.connection = None

    async def execute(
        self,
        arguments: list[str],
        java_directory: pathlib.Path,
        *,
        maximum_seconds: float,
    ) -> tests.formal.helpers.process.Result:
        """Accept a model result only after the current request has closed its output.

        Args:
            arguments: The complete TLC checker arguments, excluding JVM options.
            java_directory: A private directory for temporary modules and diagnostics.
            maximum_seconds: The execution budget once the request owns the worker.

        Returns:
            The current checker's status and full diagnostics.

        Raises:
            OSError: If the worker cannot deliver the current request's result.
            TimeoutError: If the current request exceeds its execution budget.
        """
        async with self.lock:
            if self.closed:
                message = "TLC worker is closed"
                raise OSError(message)
            self.identifier += 1
            java_directory = await asyncio.to_thread(java_directory.resolve)
            line = request_line(
                self.identifier,
                [str(java_directory), *arguments],
            )
            if self.connection is None:
                self.connection = self.start()
            connection = self.connection
            try:
                async with asyncio.timeout(maximum_seconds):
                    return await exchange(
                        connection,
                        self.identifier,
                        line,
                        java_directory,
                    )
            except TimeoutError as error:
                await self.stop()
                message = f"TLC worker request {self.identifier} timed out"
                raise TimeoutError(message) from error
            except (OSError, ValueError) as error:
                diagnostic = diagnostic_excerpt(connection)
                await self.stop()
                message = f"TLC worker request {self.identifier} failed\n{error}"
                raise OSError(f"{message}\n{diagnostic}".rstrip()) from error
            except BaseException:
                await self.stop()
                raise

    async def close(self) -> None:
        """Allow the idle worker to exit, with forced cleanup if shutdown fails.

        Raises:
            OSError: If the worker cannot complete a clean shutdown.
        """
        async with self.lock:
            self.closed = True
            if (connection := self.connection) is None:
                return
            try:
                async with asyncio.timeout(CLOSE_SECONDS):
                    await exit_after_eof(connection)
            except OSError as error:
                diagnostic = diagnostic_excerpt(connection)
                await self.stop()
                if isinstance(error, TimeoutError):
                    message = "TLC worker shutdown timed out"
                else:
                    message = str(error)
                raise OSError(f"{message}\n{diagnostic}".rstrip()) from error
            except BaseException:
                await self.stop()
                raise
            else:
                self.release(connection)
