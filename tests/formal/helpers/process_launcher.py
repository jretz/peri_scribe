"""Keep a proof tool and nested adapters inside one private process group."""

import os
import signal
import sys


def main() -> None:
    """Let nested proof adapters retain the same isolated process ownership."""
    group = os.getpgrp()
    assert group == os.getpid() == os.getsid(0)
    # Subprocess restores the signals that CPython ignores during startup.
    defaults = tuple(
        number
        for name in ("SIGPIPE", "SIGXFZ", "SIGXFSZ")
        if (number := getattr(signal, name, None)) is not None
    )
    environment = {**os.environ, "PERI_SCRIBE_FORMAL_PROCESS_GROUP": str(group)}
    command = sys.argv[1:]
    process = os.posix_spawnp(command[0], command, environment, setsigdef=defaults)
    status = os.waitstatus_to_exitcode(os.waitpid(process, 0)[1])
    if status < 0:
        if -status not in {signal.SIGKILL, signal.SIGSTOP}:
            signal.signal(-status, signal.SIG_DFL)
        os.kill(os.getpid(), -status)
    sys.exit(status)


if __name__ == "__main__":
    main()
