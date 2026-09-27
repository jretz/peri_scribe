"""Raw fire and score rows reach the complete executable notable-view policy."""

import dataclasses
import datetime
import itertools

import peri_scribe.models
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.views
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.presentation.views


EPOCH = datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC)
MISSING = -99999999
TIMES = (None, -432001, -432000, -431999, -1, 0, 1)
AREAS = (None, 0, 99, 100, 999, 1000, 1001)
BUILDINGS = (None, 0, 99, 100, 101)
POPULATION_CASE_COUNT = 648
SIGNAL_CASE_COUNT = 980
MISSING_SCORE_VARIANT = 2


def encoded(values: tuple[int | None, ...]) -> str:
    """Optional source fields remain distinguishable from meaningful zero values.

    Args:
        values: Complete raw record fields.

    Returns:
        The oracle's comma-separated representation.
    """
    return ",".join("n" if value is None else str(value) for value in values)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Fire:
    """Each source owner has independently varied eligibility and alias evidence."""

    owner: int
    name: int
    active: bool
    discovery: int | None

    def command(self) -> str:
        """Send unresolved identifiers together with the discovery evidence.

        Returns:
            The raw fire record understood by Lean.
        """
        return encoded((
            self.owner,
            self.name,
            int(self.active),
            self.discovery,
            self.owner,
            self.owner + 100,
        ))

    def actual(self) -> peri_scribe.presentation.fire_data.FireSummary:
        """Feed production selection real summaries and descriptions.

        Returns:
            The same raw identity and eligibility represented in Python.
        """
        description = peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=None
            if self.discovery is None
            else EPOCH + datetime.timedelta(seconds=self.discovery),
        )
        return dataclasses.replace(
            tests.helpers.factories.peri_scribe.presentation.views.active_fire(
                f"Fire {self.name:03}",
                identifiers=frozenset({str(self.owner), str(self.owner + 100)}),
                description=description,
            ),
            status=peri_scribe.models.FireStatus.ACTIVE
            if self.active
            else peri_scribe.models.FireStatus.INACTIVE,
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Score:
    """Distinct serials track the source of score and signal decisions together."""

    identifier: int | None
    name: int
    value: int
    area: int | None
    buildings: int | None
    evacuation: bool

    def command(self, serial: int) -> str:
        """Keep missing fields and alias scores intact for formal association.

        Args:
            serial: The source row's unique position.

        Returns:
            The complete raw score record.
        """
        return encoded((
            self.identifier,
            self.name,
            self.value,
            serial,
            self.area,
            self.buildings,
            int(self.evacuation),
        ))

    def actual(self, serial: int) -> peri_scribe.models.FireScoreEntry:
        """Store source identity in the real score's explanation field.

        Args:
            serial: The source row's unique position.

        Returns:
            The actual persisted score model.
        """
        return tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            f"Fire {self.name:03}",
            None if self.identifier is None else str(self.identifier),
            self.value,
            str(serial),
            area=self.area,
            building_count=self.buildings,
            evacuation_overlap=self.evacuation,
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """The bridge never computes selection or the active population in Python."""

    fires: tuple[Fire, ...]
    scores: tuple[Score, ...]
    now: int | None = 0

    def command(self) -> str:
        """Ask Lean to perform association, population selection, and final ranking.

        Returns:
            The complete oracle request.
        """
        return (
            f"notable {'n' if self.now is None else self.now} | "
            + " ".join(fire.command() for fire in self.fires)
            + " | "
            + " ".join(score.command(index) for index, score in enumerate(self.scores))
        )


def population_cases() -> tuple[Case, ...]:
    """Population sizes straddle every ceiling boundary through five complete fifths.

    Returns:
        Raw owners, missing scores, duplicate aliases, ties, and inactive populations.
    """
    result = []
    for count, variant in itertools.product(range(27), range(12)):
        fires = tuple(
            Fire(
                owner=index,
                name=index // 2 if variant % 3 == 0 else index,
                active=(variant % 4 != 0 and (variant % 4 == 1 or index % 3 != 0)),
                discovery=TIMES[(index + variant) % len(TIMES)],
            )
            for index in range(count)
        )
        scores = [
            Score(
                identifier=fire.owner,
                name=fire.name,
                value=10 if variant % 3 == 1 else (count - fire.owner) // 2,
                area=AREAS[(fire.owner + variant) % len(AREAS)],
                buildings=BUILDINGS[(fire.owner + variant) % len(BUILDINGS)],
                evacuation=(fire.owner + variant) % 2 == 0,
            )
            for fire in fires
            if variant % 3 != MISSING_SCORE_VARIANT or fire.owner % 3 != 1
        ]
        scores.extend(
            dataclasses.replace(
                score,
                identifier=fire.owner + 100,
                value=score.value + variant % 3 - 1,
                area=1000 if score.area is None else None,
                evacuation=not score.evacuation,
            )
            for fire, score in zip(fires, tuple(scores), strict=False)
            if fire.owner % 2 == 0
        )
        scores.extend((
            Score(
                identifier=999,
                name=999,
                value=100000,
                area=100000,
                buildings=1000,
                evacuation=True,
            ),
            Score(
                identifier=None,
                name=0,
                value=variant,
                area=100,
                buildings=100,
                evacuation=False,
            ),
        ))
        ordered = tuple(reversed(scores)) if variant % 2 else tuple(scores)
        result.extend((
            Case(fires=fires, scores=ordered),
            Case(fires=fires, scores=ordered, now=None),
        ))
    return tuple(result)


def signal_cases() -> tuple[Case, ...]:
    """An eligible high scorer separates the signal gates from score qualification.

    Returns:
        Every boundary combination of area, buildings, evacuation, and discovery time.
    """
    return tuple(
        Case(
            fires=(
                Fire(owner=0, name=0, active=True, discovery=-1),
                Fire(owner=1, name=1, active=active, discovery=time),
            ),
            scores=(
                Score(
                    identifier=0,
                    name=0,
                    value=100,
                    area=None,
                    buildings=None,
                    evacuation=False,
                ),
                Score(
                    identifier=1,
                    name=1,
                    value=0,
                    area=area,
                    buildings=buildings,
                    evacuation=evacuation,
                ),
            ),
        )
        for area, buildings, evacuation, time, active in itertools.product(
            AREAS,
            BUILDINGS,
            (False, True),
            TIMES,
            (False, True),
        )
    )


def check_cases(cases: tuple[Case, ...]) -> None:
    """Compare production's complete threshold and selected source rows with Lean.

    Args:
        cases: Unresolved source populations whose policies are computed by the oracle.
    """
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oraclePolicyDetails",
    )
    for case, (threshold, _active_count, _top_count, *selected) in zip(
        cases,
        expected,
        strict=True,
    ):
        fires = [fire.actual() for fire in case.fires]
        scores = peri_scribe.models.FireScores(
            version="formal",
            fires=[score.actual(index) for index, score in enumerate(case.scores)],
        )
        actual_threshold = peri_scribe.presentation.views.notable_score_threshold(
            fires,
            scores,
        )
        assert actual_threshold == (None if threshold == MISSING else threshold), case
        actual = peri_scribe.presentation.views.new_notable_fires(
            fires,
            scores,
            None if case.now is None else EPOCH + datetime.timedelta(seconds=case.now),
        )
        associated = {
            id(fire): entry
            for fire, entry in peri_scribe.presentation.views.matched_fire_scores(
                fires,
                scores,
            )
        }
        actual_rows = [
            value
            for fire in actual
            for value in (
                min(map(int, fire.identifiers)),
                int(associated[id(fire)].explanation),
            )
        ]
        assert actual_rows == selected, case
