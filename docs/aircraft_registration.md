# Aircraft registration recognition

`aircraft_registration.split_tail_number(text)` recognizes a complete registration at
the end of a string and returns a frozen, keyword-only `TailNumberSplit` dataclass with
`prefix` and `tail_number` fields. It returns `None` when no complete suffix matches.

```python
import aircraft_registration

aircraft_registration.split_tail_number("CA-YNP-DOME-N5852K")
# TailNumberSplit(prefix="CA-YNP-DOME", tail_number="N5852K")

aircraft_registration.split_tail_number("Dome-c-fabc")
# TailNumberSplit(prefix="Dome", tail_number="C-FABC")
```

A registration must begin the string or follow whitespace or a hyphen. The longest
matching suffix wins. Its internal hyphens remain intact. Whitespace and hyphens
separating it from the prefix are removed, and trailing whitespace is ignored. Other
prefix characters, including their case and leading whitespace, are preserved. A bare
registration returns an empty prefix. Registrations are matched using ASCII letters
and digits, case-insensitively, and returned in uppercase.

This is offline syntactic recognition. A match does not establish issuance, current
registration, airworthiness, aircraft category, or eligibility for a display exemption.
Military serials, abbreviated callsigns, and painted national emblems are outside the
API's scope. A fire name that itself ends with a syntactically valid registration can
be ambiguous; fire grouping still requires matching identifiers or compatible geography
along with the normalized name.

## Worldwide baseline

The inventory contains all 224 distinct nationality marks and the common mark `4YB` in
the [ICAO supplement dated 1 June 2025][icao-marks], linked from ICAO's
[nationality marks page][icao-page]. That supplement is an advance, unedited edition.
It includes territorial allocations, shared marks, and the notified exceptions `P`,
`RDPL`, `RP`, and `Z`. Allocations such as `VP-C` contain the hyphen and a fixed initial
registration letter; the remaining registration characters follow that allocation.

For marks without a national override, recognition uses Annex 7 sections 3.2 and 3.5:
one or more ASCII letters or digits follow the nationality/common mark, and a hyphen is
required when the registration begins with a letter. Numeric registrations may have a
hyphen. This baseline imposes no national length or allocation restrictions. In
particular, recognition under this baseline is broader than verified national syntax.

Section 3.6's explicitly identified three-letter Q combinations and the signals `SOS`,
`XXX`, `PAN`, and `TTT` are excluded as complete registration marks. Other restrictions
on allocation, including potentially confusable International Code of Signals entries,
are not exhaustively validated.

The supplement lists Andorra, Kiribati, Timor-Leste, and Tuvalu as Contracting States
without notified marks. This implementation does not invent marks for those states.
Likewise, marks absent from the supplement require an independently sourced addition.

## Verified national overrides

Sources were checked on 23 September 2026. Overrides replace the baseline for their
listed marks entirely: a malformed national registration cannot fall back to the more
permissive Annex 7 pattern. These rules recognize documented string shapes and explicit
character restrictions; they do not implement every registry's allocation policy.

| Jurisdiction | Recognition rule | Primary sources |
| --- | --- | --- |
| United States | `N` plus 1–5 digits, 1–4 digits and one letter, or 1–3 digits and two letters; no leading zero or letters `I`/`O`. | [FAA N-number rules][us] |
| US older aircraft | Optional `C`, `R`, `L`, or `X` between `N` and the registration. The displayed form is retained. | [14 CFR 45.22(b)][us-legacy] |
| Canada | `C-F`, `C-G`, or `C-I` plus three letters; legacy/vintage `CF-` plus three letters. | [Transport Canada][canada], [CAR 202.03][canada-legacy] |
| Australia | `VH-` plus three alphanumeric characters. | [CASA registration marks][australia] |
| New Zealand | `ZK-` plus three letters. Other notified marks retain baseline recognition. | [Part 47.103][new-zealand] |
| United Kingdom | `G-` plus four letters. | [CAA CAP 523, October 2024, chapter 3][uk] |
| France | `F-` plus four letters. | [Code des transports D6111-12, effective 1 November 2023][france] |
| Germany | `D-` plus four letters with category initials `A B C E F G H I K L M N O U`, or a numeric glider mark. | [LuftVZO, Anlage 1, II][germany] |
| Brazil | `PP-`, `PR-`, `PS-`, `PT-`, or `PU-` plus three letters. | [ANAC registration service][brazil] |
| Japan | `JA` plus four digits, three digits and one letter, or two digits and two letters. Suffix letters exclude `I`, `O`, `S`, and the pairs `CC` and `JA`. Numeric category allocations are not validated. | [MLIT allocation rules, used since 1996][japan] |
| Singapore | `9V-` plus three letters. | [AIP GEN 2.1.5, 12 June 2025][singapore] |

Canadian legacy marks are recognized registration forms. US antique markings are
conditional display allowances, and recognizing their spelling does not establish that
an aircraft qualifies. New Zealand Part 47 also permits shortened domestic displays,
police marks, and historical paint schemes. Those allowances do not make a bare two- or
three-letter suffix an identifiable registration in this API.

## Application integration and maintenance

Mission-name parsing owns the state/unit prefix, mapping-revision words, and the feed's
two-digit, one-letter aircraft abbreviations. It passes the remaining mission text to
this library first, then recognizes abbreviated suffixes such as `50X` and `40Y` when
no complete registration matches. Thus `CA-RRU-VISTA-50X` supplies the `VISTA` name needed
to join unnamed perimeters to their incident. The standalone registration API continues
to require a complete registration. A source incident name continues to take precedence
over a mission-derived display name. Both names remain available for matching, and
geographical grouping rules are unchanged.

The parsed-record cache version must be incremented when recognition rules change,
because it stores already-normalized names. The library's Python files participate in
source-generation and prepared-product fingerprints, invalidating derived reuse when
its code or rule inventory changes. Source snapshots remain authoritative.

For additional national overrides, consult the regulator's registration rules and the
current official AIP: GEN 2.1 for aircraft marking and GEN 1.7 for declared differences.
Record the source, applicable section, date, scope, and positive and negative examples.
Keep allocation/display conditions separate from string recognition. Update the
inventory from ICAO when a newer supplement is published; no runtime download is needed.

[icao-marks]: https://www.icao.int/sites/default/files/airnavigation/Nationality_Marks_unedited_en.pdf
[icao-page]: https://www.icao.int/nationality-marks
[us]: https://www.faa.gov/licenses_certificates/aircraft_certification/aircraft_registry/forming_nnumber
[us-legacy]: https://www.ecfr.gov/current/title-14/chapter-I/subchapter-C/part-45/subpart-C/section-45.22
[canada]: https://tc.canada.ca/en/aviation/registering-leasing-aircraft/apply-manage-reservation-aircraft-registration-mark
[canada-legacy]: https://laws-lois.justice.gc.ca/eng/regulations/SOR-96-433/section-202.03.html
[australia]: https://www.casa.gov.au/aircraft/aircraft-registration/registration-marks/reserve-aircraft-registration-mark
[new-zealand]: https://www.aviation.govt.nz/rules/rule-part/part-47/subpart-c/
[uk]: https://www.caa.co.uk/publication/download/12178
[france]: https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000023086525/LEGISCTA000048322160/2023-11-01
[germany]: https://www.gesetze-im-internet.de/luftvzo/BJNR003700964.html
[brazil]: https://www.gov.br/pt-br/servicos/matricular-aeronave-certificada
[japan]: https://www.mlit.go.jp/common/001080672.pdf
[singapore]: https://aim-sg.caas.gov.sg/aim-content/uploads/aip/21-AUG-2025/AIP/2025-08-07-000000/pdf/SG-GEN-2.1.pdf
