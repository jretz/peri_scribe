"""One vocabulary keeps command selection and recovery state consistent."""

import enum


class Stage(enum.StrEnum):
    """Stable values preserve command options and saved recovery markers."""

    FETCH = "fetch"
    GEOGRAPHY = "geography"
    SCORE = "score"
    KMZ = "kmz"
    REPORTS = "reports"
