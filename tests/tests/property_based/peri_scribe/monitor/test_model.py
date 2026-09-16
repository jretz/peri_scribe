"""Log read boundaries do not change the meaning of a stream."""

import hypothesis
import hypothesis.strategies

import peri_scribe.monitor.model
import peri_scribe.phases
import tests.helpers.factories.peri_scribe.monitor.events


@hypothesis.given(
    entries=hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            hypothesis.strategies.sampled_from(
                [
                    "Starting command",
                    "Starting phase",
                    "Finished phase",
                    "Finished command",
                    "Detail",
                ],
            ),
            hypothesis.strategies.sampled_from(["first", "second"]),
        ),
        min_size=1,
        max_size=30,
    ),
    split=hypothesis.strategies.integers(min_value=0, max_value=30),
)
def test_append_records_is_independent_of_read_batch_boundaries(
    entries: list[tuple[str, str]],
    split: int,
) -> None:
    records = tuple(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            message,
            run_id=identifier,
            command="run",
            path=(peri_scribe.phases.Segment(phase="fetch"),)
            if "phase" in message
            else (),
        )
        for message, identifier in entries
    )
    original = peri_scribe.monitor.model.State()
    complete = peri_scribe.monitor.model.append_records(original, records)
    partial = peri_scribe.monitor.model.append_records(original, records[:split])
    combined = peri_scribe.monitor.model.append_records(partial, records[split:])
    assert complete == combined
    assert original.runs == ()
