"""Exercise real executor admission, result ordering, and worker cleanup."""

from __future__ import annotations

import dataclasses
import threading

import peri_scribe.fires.sources
import peri_scribe.models
import peri_scribe.perimeters.classification_data


@dataclasses.dataclass(frozen=True, kw_only=True)
class ClassificationWorkers:
    """Coordinate the first admitted wave without relying on scheduler sleeps."""

    boundaries: peri_scribe.perimeters.classification_data.Boundaries
    barrier: threading.Barrier
    fail_first: bool = False
    hold_second: bool = False
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)
    second_started: threading.Event = dataclasses.field(default_factory=threading.Event)
    second_completed: threading.Event = dataclasses.field(
        default_factory=threading.Event,
    )
    failed: threading.Event = dataclasses.field(default_factory=threading.Event)
    release: threading.Event = dataclasses.field(default_factory=threading.Event)
    counts: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"active": 0, "peak": 0},
    )
    completions: list[int] = dataclasses.field(default_factory=list)
    threads: set[threading.Thread] = dataclasses.field(default_factory=set)

    def __call__(
        self,
        group: tuple[int, ...],
        *,
        record_groups: peri_scribe.fires.sources.FireRecordGroups,
        boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    ) -> peri_scribe.models.FireClassification:
        """Keep one worker behind a later result, or behind an observed failure.

        Args:
            group: One unique singleton group identifying the scheduled fire.
            record_groups: Complete ordered inputs supplied by the real coordinator.
            boundaries: The actual shared boundary owner passed to the workers.

        Returns:
            A distinct observable classification for this group.

        Raises:
            ValueError: The first worker is configured to fail after admission.
            TimeoutError: Another required worker was not admitted or released.
        """
        index = group[0]
        assert record_groups.groups[index] == group
        assert boundaries is self.boundaries
        with self.lock:
            self.counts["active"] += 1
            self.counts["peak"] = max(self.counts.values())
            self.threads.add(threading.current_thread())
        try:
            if index < self.barrier.parties:
                self.barrier.wait(timeout=5)
            if index == 1:
                self.second_started.set()
                if self.hold_second and not self.release.wait(timeout=5):
                    message = "The held classification worker was not released"
                    raise TimeoutError(message)
            if index == 0:
                if not self.second_started.wait(timeout=5):
                    message = "The second classification worker was not admitted"
                    raise TimeoutError(message)
                if self.fail_first:
                    self.failed.set()
                    message = "Classification worker failed"
                    raise ValueError(message)
                if not self.second_completed.wait(timeout=5):
                    message = "The later classification result did not complete"
                    raise TimeoutError(message)
            result = peri_scribe.models.FireClassification(
                classification=peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
                outside_area_fraction=index / len(record_groups.groups),
                inside_area_fraction=1 - index / len(record_groups.groups),
            )
            with self.lock:
                self.completions.append(index)
            if index == 1:
                self.second_completed.set()
            return result
        finally:
            with self.lock:
                self.counts["active"] -= 1
