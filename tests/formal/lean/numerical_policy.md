# Fractional measurements and rounded policy boundaries

`NumericalPolicy.lean` adds 18 theorems and the executable `oracleNumericalPolicy`.
It extends the integer-area policies with an explicit finite binary64 arithmetic model.
No production policy was changed for these checks.

## Arithmetic and guarantees

Each finite input is represented exactly as an integer multiple of the least positive
subnormal, `2^-1074`. The model selects a binade spacing that retains 53 significant
bits, with a minimum spacing of one subnormal unit. Subtraction, multiplication,
division, and unit scaling use exact integer ratios followed by nearest-even rounding.
The shared `CoordinateQuantization.nearest` definition supplies the proved rounding
rule, including even and odd halfway ties. Fractions are never rounded to whole acres
or square meters before comparison.

For arbitrary positive denominators, the new proofs bound rounding error by half the
selected spacing, preserve nonnegative magnitudes, and establish sign symmetry.
Publication accepts equal positive thresholds, treats growth and shrinkage equally,
and does not invent a signal from zero change. Below-threshold admission requires an
actual witness within a rounded relative-tolerance bound. A change beyond both bounds
plus the half-spacing error margin cannot be accepted. Relative comparisons include
the rounded subtraction and both rounded tolerance products used by `math.isclose`.

The report-takeover model retains subsequent-observation and baseline requirements,
minimum absolute growth, the one-day/two-confirmation rapid route, and the three-day
ordinary route. It proves that numerical rounding cannot remove the later-evidence or
minimum-age requirements. Confirmed fractional corrections remain accepted. Existing
`Scoring.tiered` proofs apply to exact common-scale integer representations of fractional
inputs and thresholds, retaining their bounds and monotonicity obligations.

## Implementation connection

Five conformance tests compare production behavior with the compiled definitions:

- **1,564 arithmetic pairs:** signed inputs, cancellation, normal/subnormal boundaries,
  adjacent floats, underflow, and deterministic generated exponents. Every subtraction,
  product, and nonzero-denominator quotient is compared exactly, without a tolerance.
- **3,750 publication comparisons:** growth and shrinkage, zero thresholds, fractional
  thresholds, large baselines, and adjacent floats at both the literal threshold and
  relative-tolerance boundary. Each comparison checks eligibility, signed change, and
  converted threshold through the actual `publication.mapping_decision`.
- **1,740 report takeovers:** fractional mapping values in square meters, acres,
  hectares, square feet, and square miles; both policy ages and their predecessors;
  distinct confirmation counts; simultaneous evidence; and equal/adjacent baselines.
- **48 acreage corrections:** strict ratio and inclusive absolute-decrease boundaries,
  with and without confirmation, through `areas.accepted_reports`.
- **80 scoring cases:** each configured tier, its immediately adjacent representable
  values, and below-threshold fractional values through `fires.scoring.tiered_points`.

The adapter sends the original finite operands, unit conversion factors, and evidence
facts. The oracle computes arithmetic and acceptance; Python does not supply an already
calculated decision or rounded difference. Conversion factors come from the installed
shared unit registry. Their physical definitions remain trusted metadata.

Operation order is part of the contract. Quantity subtraction converts the right operand
to the left operand's units. Comparisons of different units convert both operands to
base units, while equal-unit comparisons use their original magnitudes. Relative area
limits multiply in the mapping's original unit before comparison conversion. Conformance
includes a hectare/acre boundary where first converting both values to acres would erase
a real one-ULP difference and produce an incorrect oracle expectation.

## Boundaries

The unbounded proofs concern this exact integer arithmetic specification and its policy
properties. Sampled bit-exact conformance connects it to Python, Pint, and the selected
runtime; it is not a proof of the interpreter, unit registry, or hardware implementation.
All tested operations have finite results, and division cases exclude a zero denominator.
Infinity, NaN, overflow to infinity, exception behavior, and different rounding modes
are outside this model. Both signed zeros have the same comparison meaning here.

Different floating-point representations of a physical quantity can straddle a decision
boundary after conversion. These checks preserve the declared operation order and
tolerance; they do not claim exact unit invariance at every rounding boundary or add a
new tolerance to policies that currently use strict comparisons. Geometry measurement,
projection error, arbitrary policy customization, and source accuracy retain their
separate contracts. Complete candidate selection, chronology, and scoring aggregation
continue to use the existing composition proofs.
