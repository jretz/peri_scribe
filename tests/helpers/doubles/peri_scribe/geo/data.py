"""Replace data dependencies with controlled test doubles."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import arcgis.features


class QueryStub:
    """Callable that returns or raises successive outcomes from a list."""

    def __init__(self, outcomes: list[arcgis.features.FeatureSet | Exception]) -> None:
        """Initialize ordered query outcomes for retry tests.

        Args:
            outcomes: Feature sets or failures to serve on successive query attempts.
        """
        self.outcomes = list(outcomes)
        self.call_count = 0

    def query(self) -> arcgis.features.FeatureSet:
        """Serve the next configured outcome to exercise retry behavior.

        Returns:
            The feature set selected for this attempt.

        Raises:
            The configured outcome, if this attempt was assigned an exception.
        """
        outcome = self.outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class IdQueryStub:
    """Layer stand-in returning a fixed object-id query result."""

    def __init__(self, result: dict[str, object]) -> None:
        """Initialize an ID-query stub with a controlled response.

        Args:
            result: Object-ID response returned by the query stub.
        """
        self.result = result

    def query(self, **_kwargs: object) -> dict[str, object]:
        """Serve the configured object-ID response without a remote query.

        Args:
            _kwargs: Query options accepted for compatibility with ArcGIS callers.

        Returns:
            The configured object-ID response dictionary.
        """
        return self.result
