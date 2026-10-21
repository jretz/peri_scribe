"""Ordered byte identities survive duplicate inventories and mutable source bytes."""

import hashlib
import pathlib
import tempfile

import hypothesis
import hypothesis.strategies

import peri_scribe.sources.authentication


@hypothesis.settings(max_examples=30)
@hypothesis.given(
    payloads=hypothesis.strategies.lists(
        hypothesis.strategies.binary(max_size=256),
        min_size=1,
        max_size=6,
    ),
    occurrences=hypothesis.strategies.lists(
        hypothesis.strategies.integers(min_value=0, max_value=20),
        max_size=12,
    ),
    changed=hypothesis.strategies.integers(min_value=0, max_value=20),
)
def test_inventory_digests_matches_independent_sha_after_ordered_duplicate_edits(
    payloads: list[bytes],
    occurrences: list[int],
    changed: int,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = pathlib.Path(temporary)
        paths = tuple(directory / str(index) for index in range(len(payloads)))
        for path, payload in zip(paths, payloads, strict=True):
            path.write_bytes(payload)
        changed_path = paths[changed % len(paths)]
        requested = (
            *(paths[index % len(paths)] for index in occurrences),
            changed_path,
        )
        for _ in range(2):
            with peri_scribe.sources.authentication.scope(directory):
                peri_scribe.sources.authentication.file_digest(paths[0])
                assert peri_scribe.sources.authentication.inventory_digests(
                    requested,
                ) == (
                    tuple(
                        hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in requested
                    )
                )
                changed_path.write_bytes(changed_path.read_bytes() + b"edited")
                assert peri_scribe.sources.authentication.inventory_digests(
                    requested,
                ) == (
                    tuple(
                        hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in requested
                    )
                )
