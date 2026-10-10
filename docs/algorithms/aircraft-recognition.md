# Trailing aircraft registration recognition

Mission descriptions can end with a full civil aircraft registration. Recognition
separates that suffix while preserving the caller's fire-name prefix. It is an offline
syntax decision; it does not consult a registry or establish that a mark was issued.

## Contract and assessment

Input is text. Output is a preserved prefix and uppercase registration, or no match.
The [registration reference](../aircraft_registration.md) owns the sourced national
formats, dates, exclusions, and application integration rules.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 0 | Recognition depends only on the supplied string and format table. |
| Rule interaction | 2 | National overrides replace general patterns and suffix boundaries matter. |
| Mathematical reasoning | 1 | Ordered regular-expression matching uses standard string operations. |
| Scale and representation | 1 | The compiled format alternatives and candidate suffixes fit in memory. |
| Failure and concurrency | 0 | Recognition has no external effects. |

Total **4: involved**, because rule interaction exceeds 1.

## Longest eligible suffix

Candidates are examined from left to right, so the first complete suffix match is the
longest one. Internal hyphens belong to the registration once that suffix is selected.

1. Strip trailing whitespace, then consider alphanumeric positions at the start of the
   string or after whitespace or a hyphen.
2. Full-match the entire remaining suffix against the compiled format alternatives,
   case-insensitively with ASCII character semantics. The first match wins.
3. Remove separating whitespace and hyphens from the prefix's end, preserve its other
   characters and case, and uppercase only the registration.

`CA-YNP-DOME-N5852K` becomes prefix `CA-YNP-DOME` and registration `N5852K`.
`Dome-c-fabc` becomes prefix `Dome` and registration `C-FABC`. Matching only the final
hyphen-separated token would lose the Canadian prefix. A malformed national format
cannot fall through to a more permissive generic format for the same nationality mark.

## Application mission names

The application first removes a state/unit prefix only when there are enough tokens,
the state resolves, and the unit has at least three alphanumeric characters. It then
removes the full registration suffix. Only if that fails does it accept the abbreviated
two-digits-and-one-letter suffix, such as `52K`. This keeps abbreviated mission callsigns
out of the reusable civil-registration recognizer.

The resulting mission name retains its spelling. A second base-name alias removes
trailing `updated`, `update`, `revised`, `final`, and `copy` tokens repeatedly; if that
would remove every token, it retains the name. Thus `CA-YNP-Dome-Updated-N5852K` yields
mission name `Dome-Updated` and base alias `Dome`. A real name column remains preferred
for display, while normalized recorded, mission, and base names all become matching
evidence. Parsing supplies aliases; [grouping](fire-grouping-and-ownership.md) decides
whether identity and spatial evidence authorize joining observations.

## Limits, costs, and verification

There can be `O(L)` candidate boundaries in a string of length `L`; each invokes the
compiled matcher on a suffix. Total cost depends on the regex alternatives and engine
behavior, so a blanket linear bound is inappropriate. Inputs are short mission strings.
The format table is fixed during a run.

A fire name can itself end in a syntactically valid registration. The caller's identity
and geographic evidence still determine grouping. Abbreviated callsigns are handled by
the application parser, not accepted as complete civil registrations here. Registry
issuance, military serials, and unmodeled national rules remain outside this contract.

- [Parser](../../src/aircraft_registration/parsing.py) and
  [format table](../../src/aircraft_registration/formats.py).
- [Mission parsing](../../src/peri_scribe/geo/parsing.py) and
  [decoding tests](../../tests/tests/standard/peri_scribe/geo/test_parsing_decoding.py).
- [Recognition tests](../../tests/tests/standard/aircraft_registration/test_split_tail_number.py).
- [Reference and primary sources](../aircraft_registration.md) define the data policy.
  No dedicated formal model covers registry truth. This documentation change introduces
  no new parsing behavior or formal contract.
