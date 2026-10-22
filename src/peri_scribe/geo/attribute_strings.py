"""Share immutable JSON strings within one authenticated feed read.

[Attribute sharing](../../../docs/algorithms/attribute-string-sharing.md) records the
ownership, bounded-admission and exact-value arguments.
"""

from __future__ import annotations

import dataclasses


MAXIMUM_STRING_COUNT = 65_536
MAXIMUM_STRING_LENGTH = 256


@dataclasses.dataclass(frozen=True, kw_only=True)
class AttributeStrings:
    """A decoding transaction owns equal immutable leaves and separate containers."""

    values: dict[str, str] = dataclasses.field(default_factory=dict)

    def share(self, value: str) -> str:
        """Reuse exact strings while bounding the memo's extra retained storage.

        Args:
            value: A native JSON string or object key.

        Returns:
            An equal native string; admission limits never alter decoded values.
        """
        if len(value) > MAXIMUM_STRING_LENGTH:
            return value
        retained = self.values.get(value)
        if retained is not None:
            return retained
        if len(self.values) < MAXIMUM_STRING_COUNT:
            self.values[value] = value
        return value

    def leaf(self, value: object) -> object:
        """Share string leaves while retaining every JSON container's ownership.

        Args:
            value: A decoded value whose nested objects passed through the object hook.

        Returns:
            The same scalar or container, with equal shared string leaves in arrays.
        """
        if isinstance(value, str):
            return self.share(value)
        if isinstance(value, list):
            pending = [value]
            while pending:
                children = pending.pop()
                for position, child in enumerate(children):
                    if isinstance(child, str):
                        children[position] = self.share(child)
                    elif isinstance(child, list):
                        pending.append(child)
        return value

    def mapping(self, pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Decode object pairs in their original order with shared immutable leaves.

        Args:
            pairs: JSON object pairs supplied by the standard-library decoder.

        Returns:
            A fresh mutable object with standard duplicate-key behavior.
        """
        return {self.share(key): self.leaf(value) for key, value in pairs}
