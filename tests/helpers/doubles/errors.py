"""Replace errors dependencies with controlled test doubles."""

from __future__ import annotations

import typing


def raising_stub(error: BaseException) -> typing.Callable[..., typing.Never]:
    """Return a stand-in that raises *error* however it is called.

    A monkeypatched step that must fail does not care about the shape of the call, so
    one stand-in serves every signature.

    Args:
        error: The error the stand-in raises.

    Returns:
        The stand-in.
    """

    def raise_error(*args: object, **kwargs: object) -> typing.Never:
        """Raise the configured failure for an isolated dependency call.

        Args:
            args: Positional arguments accepted by the substituted dependency.
            kwargs: Keyword arguments accepted by the substituted dependency.

        Raises:
            The exception selected by the enclosing factory, on every call.
        """
        raise error

    return raise_error
