"""Produce actual checked paths for adversarial tests of the observation matcher."""

import pathlib

import tests.formal.helpers.log_rotation
import tests.formal.helpers.paths
import tests.formal.helpers.tlc


def rotation(
    directory: pathlib.Path,
) -> tuple[
    tests.formal.helpers.paths.Contract[tests.formal.helpers.log_rotation.Projection],
    tuple[tests.formal.helpers.log_rotation.Projection, ...],
]:
    """Follow exported edges, retaining all separately durable observations.

    Args:
        directory: The isolated complete TLC graph export.

    Returns:
        Its execution contract and one successful two-epoch observable path.
    """
    graph = tests.formal.helpers.tlc.graph("LogRotation", "LogRotation", directory)
    contract = tests.formal.helpers.log_rotation.contract(graph)
    initial = next(
        node for node in graph.initial if graph.states[node]["archive"] == "<<>>"
    )
    current = initial
    observations = [contract.values[current]]
    for action in (
        "Check",
        "Prepare",
        "WriteReceipt",
        "Publish",
        "RemovePlain",
        "ForgetReceipt",
        "AppendLate",
        "Check",
        "Prepare",
        "WriteReceipt",
        "Publish",
        "RemovePlain",
        "ForgetReceipt",
    ):
        successors = [
            edge.target for edge in graph.outgoing[current] if edge.action == action
        ]
        assert len(successors) == 1
        current = successors[0]
        value = contract.values[current]
        if observations[-1] != value:
            observations.append(value)
    return contract, tuple(observations)
