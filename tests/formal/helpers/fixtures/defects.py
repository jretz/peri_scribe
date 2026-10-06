"""Require one complete pristine baseline before independently isolated mutations."""

import functools
import hashlib
import pathlib

import pydantic
import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.defect_baselines
import tests.formal.helpers.defect_checks


@pytest.fixture(scope="session")
def formal_defect_baseline(
    request: pytest.FixtureRequest,
    formal_corpus_directory: pathlib.Path,
) -> tests.formal.helpers.defect_baselines.Baseline:
    """Selected mutation workers share only successful pristine execution evidence.

    Args:
        request: The complete collection retained by this worker.
        formal_corpus_directory: Shared temporary storage for this formal invocation.

    Returns:
        Passing baseline targets tied to the exact source and resource contents.
    """
    selected = tuple(
        defect
        for item in request.session.items
        if isinstance(item, pytest.Function) and hasattr(item, "callspec")
        for defect in (item.callspec.params.get("defect"),)
        if isinstance(defect, tests.formal.helpers.defect_checks.Defect)
    )
    assert selected
    identity = hashlib.sha256(
        "\n".join(defect.name for defect in selected).encode(),
    ).hexdigest()
    return tests.formal.helpers.corpus.load(
        formal_corpus_directory,
        f"defect-baseline-{identity}",
        pydantic.TypeAdapter(tests.formal.helpers.defect_baselines.Baseline),
        functools.partial(
            tests.formal.helpers.defect_baselines.check,
            tuple(
                tests.formal.helpers.defect_baselines.Target(
                    module=defect.module,
                    test=defect.test,
                )
                for defect in selected
            ),
        ),
    )
