"""Preserve real builder persistence across independent interpreter lifetimes."""

import dataclasses
import datetime
import functools
import importlib
import json
import pathlib

import peri_scribe.fire_updates
import peri_scribe.paths
import peri_scribe.pipeline_state
import peri_scribe.preparation
import peri_scribe.publication
import tests.formal.helpers.crash_worker
import tests.formal.helpers.journal
import tests.formal.helpers.journal_builder_inputs
import tests.formal.helpers.journal_wire_observer
import tests.helpers.doubles.attribute_overrides


@dataclasses.dataclass(kw_only=True)
class Builder(tests.formal.helpers.journal_wire_observer.Scenario):
    """Persist only harness identities needed to interpret a later fresh interpreter."""

    request: tests.formal.helpers.crash_worker.Request

    def inspect(self) -> None:
        """The parent checks the resulting cross-process trace against TLC edges."""
        self.request.record("observe", self.snapshot())
        payload = {
            "states": {
                key: state.model_dump(mode="json") for key, state in self.states.items()
            },
            "timestamps": {
                key: value.isoformat() for key, value in self.timestamps.items()
            },
            "batch_ids": self.batch_ids,
            "viewer_times": {
                value.isoformat(): key for value, key in self.viewer_times.items()
            },
        }
        (pathlib.Path(self.request.root) / "builder.json").write_text(
            json.dumps(payload),
        )


def run(request: tests.formal.helpers.crash_worker.Request) -> None:
    """Keep real KMZ, publication, journal, log, checkpoint, and viewer persistence.

    Args:
        request: A first publication, interrupted second publication, or fresh retry.
    """
    scenario = Builder(directory=request.directory, request=request)
    root = pathlib.Path(request.root)
    metadata = root / "builder.json"
    full = (
        importlib.import_module("tests.formal.helpers.journal_builder")
        if request.family == "builder_full"
        else None
    )
    if metadata.exists():
        payload = json.loads(metadata.read_text())
        scenario.states = {
            int(key): peri_scribe.fire_updates.State.model_validate(value)
            for key, value in payload["states"].items()
        }
        scenario.timestamps = {
            int(key): datetime.datetime.fromisoformat(value)
            for key, value in payload["timestamps"].items()
        }
        scenario.batch_ids = {
            int(key): value for key, value in payload["batch_ids"].items()
        }
        scenario.viewer_times = {
            datetime.datetime.fromisoformat(value): key
            for value, key in payload["viewer_times"].items()
        }
    directory = request.directory
    log = directory / "logs" / tests.formal.helpers.journal.LOG_NAME
    targets = {
        "kmz": peri_scribe.paths.kmz_path(directory),
        "publication": peri_scribe.publication.publication_path(directory),
        "journal": peri_scribe.fire_updates.pending_path(directory),
        "append": log,
        "checkpoint": peri_scribe.fire_updates.state_path(directory),
        "unlink journal": peri_scribe.fire_updates.pending_path(directory),
        "viewer": directory / "maps" / "updates.json",
    }
    with tests.helpers.doubles.attribute_overrides.AttributeOverrides() as patch:
        if full is None:
            assert request.builder_catalogue is not None
            patch.setattr(
                peri_scribe.preparation,
                "runtime_fingerprint",
                lambda: "formal-journal-persistence",
            )
            publish = functools.partial(
                tests.formal.helpers.journal_builder_inputs.publish_fixture,
                catalogue_path=pathlib.Path(request.builder_catalogue),
            )
        else:
            full.install(patch, scenario)
            publish = functools.partial(full.publish_fixture, fresh=True)
        tests.formal.helpers.journal_wire_observer.boundary(
            patch,
            scenario.inspect,
            None,
        )
        scenario.generation = 1 if request.phase == "seed" else 2
        if request.phase == "crash":
            request.record("event", "batch")
            tests.formal.helpers.crash_worker.interruption(
                patch,
                request,
                targets[request.boundary],
                deletion=request.boundary.startswith("unlink"),
            )
        now = tests.formal.helpers.journal.EPOCH + datetime.timedelta(
            seconds={"seed": 1, "crash": 2, "recover": 3}[request.phase],
        )
        with peri_scribe.pipeline_state.run_lock(directory) as acquired:
            assert acquired, "dead writer retained the year lock"
            publish(scenario, now)
            scenario.inspect()
    if request.phase == "seed":
        assert full is not None
        full.write_input_catalogue(
            root / tests.formal.helpers.journal_builder_inputs.CATALOGUE_NAME,
        )
    request.record("complete", request.phase)
