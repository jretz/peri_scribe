"""Connect executable Lean root constructors and field framing to actual SHA-256."""

from __future__ import annotations

import hashlib
import typing

import tests.formal.helpers.oracle
import tests.formal.helpers.source_digest


type Inventory = list[tuple[str, str]]
EMPTY_TAG = 2


def inventories() -> list[Inventory]:
    """Exercise every small tree shape with ordered edits and repeated source fields.

    Returns:
        Lengths zero through forty, their reversals, and changed final leaves.
    """
    result: list[Inventory] = []
    for size in range(41):
        original = [
            (f"火/{index % 7}\x00🔥", f"{index % 5}\x00") for index in range(size)
        ]
        result.extend((original, list(reversed(original))))
        if original:
            result.append([*original[:-1], ("", "changed\x00content")])
    result.extend(([("", "")], [("a", "one")] * 40))
    return result


def tree_tokens(leaves: typing.Sequence[tuple[int, int]]) -> list[int]:
    """Declare tree shape by recursively separating the largest complete left tree.

    Args:
        leaves: Exact string-table identities for ordered path and content pairs.

    Returns:
        Prefix constructors for transport to the actual Lean root definition.
    """
    if not leaves:
        return [EMPTY_TAG]
    if len(leaves) == 1:
        return [0, *leaves[0]]
    split = 1 << ((len(leaves) - 1).bit_length() - 1)
    return [1, *tree_tokens(leaves[:split]), *tree_tokens(leaves[split:])]


def hash_tokens(tokens: typing.Iterator[int], fields: list[bytes]) -> bytes:
    """Interpret Lean's constructor stream using trusted cryptographic hashing.

    Args:
        tokens: Constructor order emitted by executable SourceManifest.root.
        fields: UTF-8 strings framed by executable SourceDigest.fields.

    Returns:
        The constructor tree's SHA-256 digest.
    """
    tag = next(tokens)
    if tag == EMPTY_TAG:
        return hashlib.sha256(b"\x02").digest()
    if tag == 0:
        return hashlib.sha256(
            b"\x00" + fields[next(tokens)] + fields[next(tokens)],
        ).digest()
    assert tag == 1
    left = hash_tokens(tokens, fields)
    right = hash_tokens(tokens, fields)
    return hashlib.sha256(b"\x01" + left + right).digest()


def roots(cases: list[Inventory]) -> list[str]:
    """Evaluate the proved root algebra and prefix-free framing before byte hashing.

    Args:
        cases: Complete ordered inventories, each independently interpreted.

    Returns:
        Actual SHA-256 roots assembled from Lean constructor and framing outputs.
    """
    values = dict.fromkeys(value for case in cases for pair in case for value in pair)
    identities = {value: index for index, value in enumerate(values)}
    framed = tests.formal.helpers.source_digest.encode([
        (value.encode(),) for value in values
    ])
    trees = [
        tree_tokens([(identities[path], identities[content]) for path, content in case])
        for case in cases
    ]
    commands = ["manifest " + " ".join(map(str, tokens)) for tokens in trees]
    results = []
    for response in tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oraclePresentationFlow",
    ):
        tokens = iter(response)
        results.append(hash_tokens(tokens, framed).hex())
        assert next(tokens, None) is None
    return results


def inventory_keys(cases: list[Inventory]) -> list[str]:
    """Hash the actual proved fixed-pair flattening and prefix-free field encoding.

    Args:
        cases: Complete ordered source inventories.

    Returns:
        Input identities assembled from executable SourceManifest.inventoryFields.
    """
    commands = [
        "|".join((
            "inventory",
            *(
                tests.formal.helpers.source_digest.numbers(value.encode())
                for pair in case
                for value in pair
            ),
        ))
        for case in cases
    ]
    return [
        hashlib.sha256(bytes(response)).hexdigest()
        for response in tests.formal.helpers.oracle.evaluate(
            commands,
            executable="oracleSourceDigest",
        )
    ]
