"""Expose custom scalar and container behavior that native identity cannot bypass."""

from __future__ import annotations

import typing


class NeverEqualInteger(int):
    """Keep subclass equality observable even when comparing one object with itself."""

    comparisons: list[object]

    def __new__(cls, value: int) -> typing.Self:
        """Give each scalar its own comparison observations.

        Args:
            value: The underlying integer payload.

        Returns:
            A deliberately nonreflexive integer subclass.
        """
        result = super().__new__(cls, value)
        result.comparisons = []
        return result

    def __eq__(self, other: object) -> bool:
        """Record the operand and reject equality.

        Args:
            other: The compared object.

        Returns:
            False, including comparison with this exact object.
        """
        self.comparisons.append(other)
        return False

    __hash__ = int.__hash__


class TracedFloat(float):
    """Make the existing hexadecimal subclass dispatch visible."""

    encodings: list[str]

    def __new__(cls, value: float) -> typing.Self:
        """Keep hexadecimal observations separate for each instance.

        Args:
            value: The underlying floating-point payload.

        Returns:
            A float whose encoding calls can be observed.
        """
        result = super().__new__(cls, value)
        result.encodings = []
        return result

    def hex(self) -> str:
        """Retain the exact native encoding while recording its evaluation.

        Returns:
            The native hexadecimal floating-point representation.
        """
        encoded = super().hex()
        self.encodings.append(encoded)
        return encoded


def inconsistent_length_lists() -> tuple[list[object], list[object]]:
    """Build custom list inputs whose advertised and iterated lengths disagree.

    Returns:
        Lists of one concrete subclass with equal declared lengths and unequal contents.
    """

    def declared_length(_values: list[object]) -> int:
        """Supply equal declared lengths while leaving actual iteration intact.

        Returns:
            One, independent of the stored number of children.
        """
        return 1

    kind = type("InconsistentLengthList", (list,), {"__len__": declared_length})
    return kind([1]), kind([1, 2])


def traced_dictionaries(
    events: list[str],
) -> tuple[dict[str, object], dict[str, object]]:
    """Build supported custom mapping inputs with observable comparison operations.

    Args:
        events: Receives each validation, traversal and value lookup in order.

    Returns:
        Equal dictionaries of one concrete subclass retaining ordinary mapping views.
    """
    labels: dict[int, str] = {}

    def iterate(dictionary: dict[str, object]) -> typing.Iterator[str]:
        """Observe initial key validation while retaining native iteration.

        Returns:
            An iterator over the ordinary stored keys.
        """
        events.append(f"{labels[id(dictionary)]}:iter")
        return iter(dict.keys(dictionary))

    def keys(dictionary: dict[str, object]) -> typing.KeysView[str]:
        """Observe native key-set comparison.

        Returns:
            The native key view.
        """
        events.append(f"{labels[id(dictionary)]}:keys")
        return dict.keys(dictionary)

    def items(dictionary: dict[str, object]) -> typing.ItemsView[str, object]:
        """Observe recursive content traversal.

        Returns:
            The native ordered item view.
        """
        events.append(f"{labels[id(dictionary)]}:items")
        return dict.items(dictionary)

    def item(dictionary: dict[str, object], key: str) -> object:
        """Observe the current right-hand value lookup.

        Returns:
            The ordinary stored value for the known source key.
        """
        events.append(f"{labels[id(dictionary)]}:get:{key}")
        return dict.get(dictionary, key)

    kind = type(
        "TracedDictionary",
        (dict,),
        {"__iter__": iterate, "keys": keys, "items": items, "__getitem__": item},
    )
    left, right = kind(value=1), kind(value=1)
    labels[id(left)], labels[id(right)] = "left", "right"
    return left, right


def unusual_metaclass_value(*, unhashable: bool) -> object:
    """Make unsupported values whose class cannot safely enter a native-type set.

    Args:
        unhashable: Make the class unhashable; otherwise spoof equality with str.

    Returns:
        An unsupported object with an unhashable or equality-spoofing metaclass.
    """

    def same_type(_left: object, _right: object) -> bool:
        """Pretend this unsupported class is any requested native class.

        Returns:
            True for every purported class comparison.
        """
        return True

    def native_hash(_kind: object) -> int:
        """Route the spoofing class into str's native hash bucket.

        Returns:
            The hash of the native str class.
        """
        return hash(str)

    metaclass = type(
        "UnusualMetaclass",
        (type,),
        {"__hash__": None if unhashable else native_hash, "__eq__": same_type},
    )
    kind = metaclass("UnsupportedValue", (), {})
    return kind()
