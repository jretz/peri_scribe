# Raw feed decoding

`PeriScribe/RawDecoding.lean` contains 21 checked theorems. `OracleRawDecoding.lean`
executes those same definitions; `oracleRawDecoding` is the conformance reference.

## Contract and implementation owners

- `geo/parsing.py::numeric_value` admits finite real numbers and numeric text, preserves
  zero, and rejects missing values, Booleans, nonfinite values, malformed text, and
  conversion overflow.
- `geo/parsing.py::observation_time_from` parses ISO text and datetime objects, assumes
  UTC for naive values, and returns a UTC instant or missing when conversion is invalid
  or exceeds the representable calendar.
- `sources/changes.py::modified_datetime_from` also accepts ArcGIS epoch milliseconds.
- `perimeters/history_attributes.py::{typed_attribute,text_attribute,float_attribute,
  datetime_attribute}` selects the first usable typed value in declared column order.
  Blank or malformed candidates cannot mask a valid fallback. The separate raw
  `attribute_value` helper deliberately retains its first-present contract.
- `perimeters/versions.py::effective_time` binds typed date fallback to the actual
  perimeter chronology: a valid row edit date precedes the snapshot date.

## Unbounded guarantees

The selection algorithm agrees with the head of all successful parses. A successful
result has a precise witness: a field yielding that value, preceded only by unusable
fields. Missing is returned exactly when every candidate is unusable. Selection over
concatenated field groups agrees with selecting each group in priority order; adding a
suffix cannot change an earlier successful result. An unusable prefix is irrelevant,
and every returned value comes from an input. Zero, missing, Boolean, malformed, and
nonfinite cases are explicitly distinguished.

Timestamp normalization uses exact integer microseconds. A successful UTC conversion
is within Python datetime's calendar bounds. Shifting a wall clock and its offset by
the same amount preserves its instant. UTC normalization is idempotent; equivalent
representations agree, and a fixed offset preserves ordering. Integral epoch
milliseconds agree with UTC normalization, including epoch zero. These arithmetic and
field-order theorems have no list-length or timestamp-magnitude bound.

## Implementation connection

`conformance/test_raw_decoding.py` exercises production code against 6,213 compiled
oracle results:

- 56 numeric scalar representations and 1,897 numeric field sequences;
- 1,783 text field sequences;
- 92 timestamp representations through each of the observation and modified parsers,
  plus 2,005 datetime field sequences;
- 288 combinations of actual perimeter edit-date and snapshot fallback.

The catalogue includes absent fields, pandas nulls, whitespace and Unicode whitespace,
invalid syntax, Boolean values, infinities, overflowing numbers, signed zero, subnormal
numbers, timezone offsets, leap dates, and both calendar boundaries. Every type covers
all triples of twelve representative fields, then wider representation variants in
several priority positions. Dictionary insertion order is reversed independently of
declared field order. Numeric payloads are encoded by exact binary64 bits, and actual
UTC datetime results by integer microseconds. The adapter never calls a production
parser to construct the oracle's inputs or calculates a second Python field-selection
policy.

The decoding work exposed suppressed valid fallback fields, admitted nonfinite numbers,
and exceptions for unrepresentable UTC timestamps. Twenty-five ordinary regression
cases were confirmed failing before production fixes and passing afterward, in
`test_parsing_decoding.py`, `test_changes_decoding.py`, and
`test_history_attributes_decoding.py` under the corresponding standard-test owners.

## Boundaries

The model starts with a candidate classified for its requested type. A numeric Boolean
is unusable; a Boolean rendered as text retains the existing text-conversion policy.
Lexical ISO parsing, Unicode stripping, pandas null detection, Python's calendar, and
IEEE float conversion are library boundaries, exercised by conformance rather than
proved in Lean. Finite numeric values are opaque payload identities; the model proves
selection and preservation, not decimal-to-binary rounding or downstream arithmetic.

Timestamp proofs use exact integer microseconds and integral epoch milliseconds. The
bridge's numeric-date catalogue uses integral values whose conversion is exact in the
tested runtime, including whole seconds at calendar boundaries. Fractional epoch
milliseconds and floating conversion error for other magnitudes are outside the proof.
Source timestamps' truth, geographic validity, and fire identity are separate contracts.
