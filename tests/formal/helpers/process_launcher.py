"""Keep a proof tool and nested adapters inside one private process group."""

import asyncio
import os
import signal
import sys


async def main() -> None:
    """Let nested proof adapters retain the same isolated process ownership."""
    group = os.getpgrp()
    assert group == os.getpid() == os.getsid(0)
    environment = {**os.environ, "PERI_SCRIBE_FORMAL_PROCESS_GROUP": str(group)}
    process = await asyncio.create_subprocess_exec(*sys.argv[1:], env=environment)
    status = await process.wait()
    if status < 0:
        if -status not in {signal.SIGKILL, signal.SIGSTOP}:
            signal.signal(-status, signal.SIG_DFL)
        os.kill(os.getpid(), -status)
    sys.exit(status)


if __name__ == "__main__":
    asyncio.run(main())
