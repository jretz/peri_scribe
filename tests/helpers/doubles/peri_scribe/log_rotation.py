"""Interrupt one durable log-rotation mutation without replacing filesystem behavior."""

import dataclasses
import pathlib
import typing


if typing.TYPE_CHECKING:
    import pytest


class ProcessLoss(BaseException):
    """Leave durable files at a selected boundary outside ordinary recovery."""


@dataclasses.dataclass(kw_only=True)
class Interruption:
    """Locate one replacement or deletion and retain whether it was exercised."""

    target: pathlib.Path
    deletion: bool
    after: bool
    reached: bool = False

    def check(self, path: pathlib.Path, *, deletion: bool, after: bool) -> None:
        """Interrupt once at the configured physical mutation boundary.

        Args:
            path: Published or removed path.
            deletion: Whether the boundary removes a file.
            after: Whether the mutation already completed.

        Raises:
            ProcessLoss: The configured interruption boundary was reached.
        """
        if (
            not self.reached
            and path == self.target
            and deletion == self.deletion
            and after == self.after
        ):
            self.reached = True
            raise ProcessLoss

    def install(self, patch: pytest.MonkeyPatch) -> None:
        """Leave every successful replacement and deletion on real temporary files.

        Args:
            patch: Isolated monkeypatch scope.
        """
        original_replace = pathlib.Path.replace
        original_unlink = pathlib.Path.unlink

        def replace(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
            """Expose both sides of one atomic replacement.

            Args:
                path: The staged input.
                target: The published destination.

            Returns:
                The real replacement result.
            """
            self.check(target, deletion=False, after=False)
            result = original_replace(path, target)
            self.check(target, deletion=False, after=True)
            return result

        def unlink(path: pathlib.Path, *, missing_ok: bool = False) -> None:
            """Expose both sides of source or receipt retirement.

            Args:
                path: The retired file.
                missing_ok: Whether already absent files are permitted.
            """
            self.check(path, deletion=True, after=False)
            original_unlink(path, missing_ok=missing_ok)
            self.check(path, deletion=True, after=True)

        patch.setattr(pathlib.Path, "replace", replace)
        patch.setattr(pathlib.Path, "unlink", unlink)
