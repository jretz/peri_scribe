# Deliberate defect checks

`conformance/test_defect_checks.py` checks that established conformance tests detect
twenty specific production defects. One pristine interpreter executes every unique
selected target against private copied source packages. Workers share the complete
successful baseline through the current run's atomic corpus. Each case copies the
source packages into its own temporary directory, requires every source and resource
digest to match that baseline, changes one expression inside one named production
function, and reruns its established check in a fresh interpreter. Repository source
files and Lean/TLA+ specifications are not changed.

| Deliberate defect | Existing check required to fail |
| --- | --- |
| Render source Markdown without escaping its structural characters | Lean literal-text encoding and source preservation contract |
| Read a late plain tail before its archived prefix | Lean occurrence order composed with saved snapshot predecessors |
| Widen the publication comparison's relative tolerance | Rounded binary64 reference at fractional conversion and tolerance boundaries |
| Treat an invalid authoritative checkpoint or journal as missing | TLC validation paths through real recovery, journal publication, and viewer writes |
| Compute previous acreage within the original bucket instead of its current owner | Lean composition of ownership projection and the complete chronological snapshot |
| Accept equal coordinates under different coordinate reference systems | Lean relational coverage and complete source-validation diagnostics |
| Hide duplicate source IDs during validation | Lean unique-row coverage and complete source-validation diagnostics |
| Stop log reading at the first timestamp above the upper bound | Lean occurrence completeness including subsequent undated diagnostics |
| Omit derived-stage requirements before source mutation in `run_fetch_stage` | TLC fetch-interruption replay, including unchanged retries |
| Accept unrelated authenticated full/differential geography generations | Continuous TLC reader execution against actual GeoPackages and signatures |
| Omit the chart axis label from its cache key | Lean dependency contract and actual persistent-cache/fresh rendering comparison |
| Make score threshold equality exclusive | Lean score policy at tier boundaries |
| Remove source fingerprint field framing | Lean's exact byte encoder and actual source encoding |
| Omit source attribute names from schema identity | Lean schema-and-row-bag equivalence against real dataframe digests |
| Bypass recovery of a pending log rotation | TLC durable-state replay with interrupted actual archive replacement and retirement |
| Omit an archive prefix while its month has a late plain tail | TLC reader observations against complete production reads |
| Temporarily roll back an acknowledged checkpoint | One continuous TLC execution through actual builder writes |
| Accept a nonfinite raw number | Lean's typed decoding reference |
| Permit monitor publication after session stop | Continuous TLC execution of domain requests and descriptor retirement |
| Give undated history claims priority over dated mapping | Lean raw-alias claim selection and real unique writer allocation |

The helper confirms the interpreter loaded the temporary production module. Source
matching must find exactly one expression in the intended function, and the changed
source must parse. A pristine failure, missing collected test, syntax error, process
timeout, or tool failure cannot stand in for successful defect detection. The mutant
must fail the named test with its expected semantic assertion or missing-exception
diagnostic. Fixtures and conformance assertions are unchanged in both executions.

Independent defect cases use the formal suite's parallel workers. Twenty mutations
have nineteen unique target checks, so a complete run uses one pristine baseline
interpreter and twenty isolated mutant interpreters. Each nested pytest session stays
serial, preserving isolated source imports and avoiding nested worker pools. The baseline
report must contain exactly the selected target identities with no skipped, failed, or
error outcomes. Checked TLC graphs remain shared within the outer formal invocation;
production executions and mutated source trees remain independent.

These checks run inside `mise formal-conformance` and the full `mise formal`. Run only
these checks with `mise formal-defects`. They demonstrate sensitivity to these twenty
regressions, not that all possible defects will be detected. When implementation
structure changes, update the mutation location while retaining the violated behavioral
contract and independent failing check.
