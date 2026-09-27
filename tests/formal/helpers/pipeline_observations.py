"""Keep observer regressions independent of checked transition expectations."""

import pathlib

import peri_scribe.pipeline_state
import peri_scribe.publication
import tests.formal.helpers.pipeline_composition
import tests.helpers.factories.peri_scribe.publication


def scenario(
    directory: pathlib.Path,
) -> tests.formal.helpers.pipeline_composition.Replay:
    """Use real durable files while a test records observations at mutation boundaries.

    Args:
        directory: Isolated year storage owned by one observer regression.

    Returns:
        An initialized invocation with distinct source and output artifacts.
    """
    durable = tests.formal.helpers.pipeline_composition.Durable(
        source=0,
        outputs=(0, 0, 0, 0),
        pending=peri_scribe.pipeline_state.PendingRun(),
        deferred=True,
        kmz_version=0,
        publication_version=0,
        publication=0,
    )
    replay = tests.formal.helpers.pipeline_composition.Replay(
        invocation=tests.formal.helpers.pipeline_composition.Invocation(
            before=durable,
            after=durable,
            first=0,
            last=4,
            gated=True,
            forced=False,
            changed=False,
            threshold=True,
            current=0,
            failed_at="",
            executed=(),
            forces=(),
        ),
        directory=directory,
    )
    replay.initialize()
    return replay


def mutate(
    replay: tests.formal.helpers.pipeline_composition.Replay,
    boundary: str,
) -> None:
    """Complete an actual watched operation after unrelated durable fields change.

    Args:
        replay: The observer's private source, outputs, markers, and publication.
        boundary: One filesystem operation intercepted by the boundary observer.

    Raises:
        AssertionError: If the selected boundary is not instrumented.
    """
    directory = replay.directory
    publication = peri_scribe.publication.publication_path(directory)
    match boundary:
        case "pending replace":
            peri_scribe.pipeline_state.write_state(
                directory,
                peri_scribe.pipeline_state.PendingRun(
                    remaining=peri_scribe.pipeline_state.DERIVED_STAGES,
                    unconditional=True,
                ),
            )
        case "publication replace":
            peri_scribe.publication.write_state(
                publication,
                tests.helpers.factories.peri_scribe.publication.publication(
                    tests.formal.helpers.pipeline_composition.THRESHOLD_CHANGE_MAPPING,
                ),
            )
        case "pending unlink":
            peri_scribe.pipeline_state.state_path(directory).unlink()
        case "publication unlink":
            publication.unlink()
        case "deferred touch":
            peri_scribe.pipeline_state.defer_inputs(directory)
        case "deferred unlink":
            peri_scribe.pipeline_state.clear_deferred_inputs(directory)
        case _:
            message = f"Unknown observation boundary: {boundary}"
            raise AssertionError(message)
