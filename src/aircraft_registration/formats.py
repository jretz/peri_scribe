"""Sourced recognition rules; allocation and display eligibility stay with registries.

The notified-mark inventory comes from the 1 June 2025 supplement to ICAO Annex 7.
The accompanying source catalog in ``docs/aircraft_registration.md`` records national
rules and their scope. No network access is needed to import or use these rules.
"""

from __future__ import annotations

import dataclasses
import re


ICAO_SOURCE = (
    "https://www.icao.int/sites/default/files/airnavigation/"
    "Nationality_Marks_unedited_en.pdf"
)

# Territorial allocations retain their embedded hyphens and fixed registration letter.
# National emblems are visual markings, so only their associated textual marks appear.
NATIONALITY_MARKS = frozenset(
    [
        "2",
        "3A",
        "3B",
        "3C",
        "3DC",
        "3X",
        "4K",
        "4L",
        "4O",
        "4R",
        "4X",
        "4Z",
        "5A",
        "5B",
        "5H",
        "5N",
        "5R",
        "5T",
        "5U",
        "5V",
        "5W",
        "5X",
        "5Y",
        "6O",
        "6V",
        "6W",
        "6Y",
        "7O",
        "7P",
        "7Q",
        "7T",
        "8P",
        "8Q",
        "8R",
        "9A",
        "9G",
        "9GR",
        "9H",
        "9J",
        "9K",
        "9L",
        "9M",
        "9N",
        "9Q",
        "9U",
        "9V",
        "9XR",
        "9Y",
        "A2",
        "A3",
        "A4O",
        "A5",
        "A6",
        "A7",
        "A8",
        "A9C",
        "AP",
        "B",
        "C",
        "C2",
        "C5",
        "C6",
        "C9",
        "CC",
        "CF",
        "CN",
        "CP",
        "CR",
        "CS",
        "CU",
        "CX",
        "D",
        "D2",
        "D4",
        "D6",
        "DQ",
        "E3",
        "E5",
        "E7",
        "EC",
        "EI",
        "EJ",
        "EK",
        "EP",
        "ER",
        "ES",
        "ET",
        "EW",
        "EX",
        "EY",
        "EZ",
        "F",
        "G",
        "H4",
        "HA",
        "HB",
        "HC",
        "HH",
        "HI",
        "HJ",
        "HK",
        "HL",
        "HP",
        "HR",
        "HS",
        "HZ",
        "I",
        "J2",
        "J3",
        "J5",
        "J6",
        "J7",
        "J8",
        "JA",
        "JU",
        "JY",
        "LN",
        "LQ",
        "LV",
        "LX",
        "LY",
        "LZ",
        "M",
        "N",
        "OB",
        "OD",
        "OE",
        "OH",
        "OK",
        "OM",
        "OO",
        "OY",
        "P",
        "P2",
        "P4",
        "PH",
        "PJ",
        "PK",
        "PP",
        "PR",
        "PS",
        "PT",
        "PU",
        "PZ",
        "RA",
        "RDPL",
        "RP",
        "S2",
        "S5",
        "S7",
        "S9",
        "SE",
        "SP",
        "ST",
        "SU",
        "SX",
        "T7",
        "T8",
        "TC",
        "TF",
        "TG",
        "TI",
        "TJ",
        "TL",
        "TN",
        "TR",
        "TS",
        "TT",
        "TU",
        "TY",
        "TZ",
        "UK",
        "UP",
        "UR",
        "V2",
        "V3",
        "V4",
        "V5",
        "V6",
        "V7",
        "V8",
        "VH",
        "VP-A",
        "VP-B",
        "VP-C",
        "VP-F",
        "VP-G",
        "VP-L",
        "VP-M",
        "VQ-B",
        "VQ-C",
        "VQ-H",
        "VQ-T",
        "VT",
        "XA",
        "XB",
        "XC",
        "XT",
        "XU",
        "XV",
        "XY",
        "XZ",
        "YA",
        "YI",
        "YJ",
        "YK",
        "YL",
        "YN",
        "YR",
        "YS",
        "YU",
        "YV",
        "Z",
        "Z3",
        "Z8",
        "ZA",
        "ZJ",
        "ZK",
        "ZL",
        "ZM",
        "ZP",
        "ZS",
        "ZT",
        "ZU",
    ],
)

COMMON_MARKS = frozenset({"4YB"})

# Annex 7 section 3.6 explicitly names these reserved signal combinations. Other
# allocation restrictions, including International Code of Signals conflicts, require
# registry knowledge and are outside syntactic recognition.
SIGNAL_EXCLUSION = r"(?!(?:Q[A-Z]{2}|SOS|XXX|PAN|TTT)\Z)"


@dataclasses.dataclass(frozen=True, kw_only=True)
class NationalFormat:
    """Associate a national override with the marks it replaces and its authority."""

    marks: tuple[str, ...]
    pattern: str
    source: str


NATIONAL_FORMATS = (
    NationalFormat(
        marks=("N",),
        pattern=(
            r"N[CRLX]?(?:[1-9][0-9]{0,4}|[1-9][0-9]{0,3}[A-HJ-NP-Z]|"
            r"[1-9][0-9]{0,2}[A-HJ-NP-Z]{2})"
        ),
        source=(
            "https://www.faa.gov/licenses_certificates/aircraft_certification/"
            "aircraft_registry/forming_nnumber"
        ),
    ),
    NationalFormat(
        marks=("C", "CF"),
        pattern=r"(?:C-[FGI][A-Z]{3}|CF-" + SIGNAL_EXCLUSION + r"[A-Z]{3})",
        source="https://laws-lois.justice.gc.ca/eng/regulations/SOR-96-433/section-202.03.html",
    ),
    NationalFormat(
        marks=("VH",),
        pattern=r"VH-" + SIGNAL_EXCLUSION + r"[A-Z0-9]{3}",
        source=(
            "https://www.casa.gov.au/aircraft/aircraft-registration/"
            "registration-marks/reserve-aircraft-registration-mark"
        ),
    ),
    NationalFormat(
        marks=("ZK",),
        pattern=r"ZK-" + SIGNAL_EXCLUSION + r"[A-Z]{3}",
        source="https://www.aviation.govt.nz/rules/rule-part/part-47/subpart-c/",
    ),
    NationalFormat(
        marks=("G",),
        pattern=r"G-[A-Z]{4}",
        source="https://www.caa.co.uk/publication/download/12178",
    ),
    NationalFormat(
        marks=("F",),
        pattern=r"F-[A-Z]{4}",
        source=(
            "https://www.legifrance.gouv.fr/codes/section_lc/"
            "LEGITEXT000023086525/LEGISCTA000048322160/2023-11-01"
        ),
    ),
    NationalFormat(
        marks=("D",),
        pattern=r"D-(?:[ABCEFGHIKLMNOU][A-Z]{3}|[0-9]+)",
        source="https://www.gesetze-im-internet.de/luftvzo/BJNR003700964.html",
    ),
    NationalFormat(
        marks=("PP", "PR", "PS", "PT", "PU"),
        pattern=r"P[PRSTU]-" + SIGNAL_EXCLUSION + r"[A-Z]{3}",
        source="https://www.gov.br/pt-br/servicos/matricular-aeronave-certificada",
    ),
    NationalFormat(
        marks=("JA",),
        pattern=(
            r"JA(?:[0-9]{4}|[0-9]{3}[A-HJ-NP-RT-Z]|"
            r"[0-9]{2}(?!CC|JA)[A-HJ-NP-RT-Z]{2})"
        ),
        source="https://www.mlit.go.jp/common/001080672.pdf",
    ),
    NationalFormat(
        marks=("9V",),
        pattern=r"9V-" + SIGNAL_EXCLUSION + r"[A-Z]{3}",
        source=(
            "https://aim-sg.caas.gov.sg/aim-content/uploads/aip/21-AUG-2025/"
            "AIP/2025-08-07-000000/pdf/SG-GEN-2.1.pdf"
        ),
    ),
)


def registration_patterns() -> tuple[str, ...]:
    """Refine the complete notified-mark inventory with documented national syntax.

    Annex 7 requires a hyphen before a registration starting with a letter; a numeric
    registration may follow its nationality mark directly. National rules replace that
    baseline entirely, so malformed registrations cannot fall back to looser syntax.

    Returns:
        Complete registration expressions, suitable for ASCII case-insensitive matches.
    """
    overridden = {mark for rule in NATIONAL_FORMATS for mark in rule.marks}
    patterns = [rule.pattern for rule in NATIONAL_FORMATS]
    for mark in sorted((NATIONALITY_MARKS | COMMON_MARKS) - overridden):
        if "-" in mark:
            patterns.append(re.escape(mark) + r"[A-Z0-9]+")
        else:
            patterns.append(
                re.escape(mark)
                + r"(?:-"
                + SIGNAL_EXCLUSION
                + r"[A-Z0-9]+|[0-9][A-Z0-9]*)",
            )
    return tuple(patterns)
