"""Keep stage-policy fixtures local while exercising the real segment coordinator."""

import asyncio
import pathlib
import signal

import peri_scribe.supervision


class DelayedLaunch:
    """Hold actual process creation until repeated cancellation has been requested."""

    def __init__(self) -> None:
        """Retain the genuine launcher and independent admission and release gates."""
        self.launch = asyncio.create_subprocess_exec
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.process: asyncio.subprocess.Process | None = None

    async def __call__(
        self,
        *command: str,
        pass_fds: tuple[int, ...],
        start_new_session: bool,
    ) -> asyncio.subprocess.Process:
        """Expose cancellation before the operating system returns a process handle.

        Args:
            command: Actual shell-free child arguments.
            pass_fds: Actual inherited writer descriptor.
            start_new_session: Production group-isolation policy.

        Returns:
            The genuine newly created process after the gate is released.
        """
        self.entered.set()
        await self.release.wait()
        self.process = await self.launch(
            *command,
            pass_fds=pass_fds,
            start_new_session=start_new_session,
        )
        return self.process


def thread_signal_scopes() -> tuple[object, object]:
    """Exercise worker-thread callers without attempting global signal changes.

    Returns:
        The unchanged interrupt and termination handlers inside both scopes.
    """
    with (
        peri_scribe.supervision.deferred_interrupts(),
        peri_scribe.supervision.termination_cleanup(),
    ):
        return signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)


def inline_child(
    request: peri_scribe.supervision.Request,
    descriptor: int,
    directory: pathlib.Path,
) -> peri_scribe.supervision.SegmentResult:
    """Replace only process transport so existing stage doubles stay visible.

    Args:
        request: The real coordinator's selected segment and frozen inputs.
        descriptor: Parent lease, retained by the actual command context.
        directory: Private transport directory, unused by the in-process adapter.

    Returns:
        The real pipeline loop's completed segment result.
    """
    return peri_scribe.supervision.execute_request(request)
