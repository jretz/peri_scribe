"""Expose mutable subclass behavior and count actual lexical derivations."""

from __future__ import annotations

import abc
import collections.abc
import dataclasses
import pathlib
import typing


class ChangingPath(pathlib.PosixPath):
    """Make a custom relative_to result change independently of its lexical key."""

    result: str = "first"

    def relative_to(self, *args: object, **kwargs: object) -> typing.Self:
        """Return the currently requested custom result.

        Args:
            args: The caller's positional provenance arguments.
            kwargs: The caller's keyword provenance arguments.

        Returns:
            A path containing this instance's current custom result.
        """
        del args, kwargs
        return type(self)(self.result)


class CustomDirectory(pathlib.PurePosixPath):
    """Keep custom directory types distinct from the stock immutable domain."""


class StockEqualMetaclass(abc.ABCMeta):
    """Let a custom class compare equal to stock PosixPath without being identical."""

    def __eq__(cls, other: object) -> bool:
        """Spoof stock class membership while preserving comparison with itself.

        Args:
            other: The class being compared by a membership operation.

        Returns:
            Whether this object is itself or the stock PosixPath class.
        """
        return cls is other or other is pathlib.PosixPath

    __hash__ = type.__hash__


class StockEqualPath(ChangingPath, metaclass=StockEqualMetaclass):
    """Combine changing relative results with spoofed stock class equality."""


class DirectoryAwarePath(pathlib.PurePosixPath):
    """Make same-spelling custom directory objects observably different operands."""

    def relative_to(self, other: object, **kwargs: object) -> typing.Self:
        """Expose the exact custom directory object's state consumed by the call.

        Args:
            other: A custom directory carrying a current result label.
            kwargs: Unused path traversal options.

        Returns:
            The directory's current label as a lexical path.
        """
        del kwargs
        return type(self)(typing.cast("ChangingPath", other).result)


@dataclasses.dataclass(kw_only=True)
class RelativeCalls:
    """Count derivations while preserving the actual lexical implementation."""

    original: collections.abc.Callable[
        [pathlib.PurePath, pathlib.PurePath],
        pathlib.PurePath,
    ]
    calls: list[tuple[pathlib.PurePath, pathlib.PurePath]] = dataclasses.field(
        default_factory=list,
    )

    def __call__(
        self,
        path: pathlib.PurePath,
        other: pathlib.PurePath,
    ) -> pathlib.PurePath:
        """Retain one observation per actual relative_to call.

        Args:
            path: The source path being converted.
            other: Its lexical directory.

        Returns:
            The original method's exact result.
        """
        self.calls.append((path, other))
        return self.original(path, other)

    def method(
        self,
    ) -> collections.abc.Callable[
        [pathlib.PurePath, pathlib.PurePath],
        pathlib.PurePath,
    ]:
        """Bind recording through an ordinary method descriptor on the Path class.

        Returns:
            A function whose first argument remains the source Path instance.
        """

        def relative(
            path: pathlib.PurePath,
            other: pathlib.PurePath,
        ) -> pathlib.PurePath:
            """Delegate the bound Path call to this recorder.

            Args:
                path: The current source path.
                other: Its lexical provenance directory.

            Returns:
                The current lexical relative path.
            """
            return self(path, other)

        return relative
