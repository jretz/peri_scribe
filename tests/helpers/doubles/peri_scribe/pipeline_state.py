"""Replace pipeline state dependencies with controlled test doubles."""

import pathlib
import typing

import peri_scribe.pipeline_state


def make_interrupted_locked_run(
    *,
    tmp_path: pathlib.Path,
) -> typing.Callable[..., None]:
    """Create a callback with controlled dependencies.

    Interrupt a locked run to exercise lock release during failure.

    Args:
        tmp_path: Isolated directory used by the callback.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def interrupted_run() -> None:
        """Interrupt a locked run to exercise lock release during failure.

        Raises:
            ValueError: Always, after checking that a second writer is excluded.
        """
        with peri_scribe.pipeline_state.run_lock(tmp_path) as first:
            assert first
            with peri_scribe.pipeline_state.run_lock(tmp_path) as second:
                assert not second
            message = "interrupted"
            raise ValueError(message)

    return interrupted_run


def fail_marker_replacement(_self: pathlib.Path, _target: pathlib.Path) -> None:
    """Simulate failed publication of a replacement recovery marker.

    Args:
        _self: Path receiving the intercepted filesystem operation.
        _target: Replacement destination accepted by the failing operation.

    Raises:
        OSError: Always, to exercise preservation of the previous marker.
    """
    message = "interrupted"
    raise OSError(message)
