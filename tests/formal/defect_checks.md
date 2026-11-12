# Deliberate defect checks

Passing against the current implementation doesn't show that a test would catch a bug.
`conformance/test_defect_checks.py` checks that the established conformance tests reject
twenty specific production defects after passing against unchanged source.

One fresh interpreter checks all nineteen unique targets against an unchanged private
source tree. Each of the twenty mutations then gets a separate private source tree and
fresh interpreter. Native imports bind each test to its actual changed source. The
source/resource hashes must match the passing baseline before the mutation is applied.
Repository source files, Lean/TLA+ specifications and conformance assertions remain
unchanged.

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

Isolated interpreters use pytest's `--assert=plain` mode to execute the original Python
assertions. Source-expression diagnostics then use the current import location. This
avoids pytest-rewritten bytecode retaining another checkout's absolute source paths after
a directory is copied. The original assertion conditions and strict rejection checks
still apply. The outer conformance suite retains its ordinary assertion rewriting.

Each mutant must produce exactly one native JUnit testcase with its expected identity
and semantic failure. Missing results, skips, additional cases, and setup or teardown
errors reject the check. Process exit and diagnostics must also agree with that failure.
The existing process owner joins descendants before releasing their temporary files.
Checked TLC graphs remain shared within the outer formal invocation; mutable test data
and mutation verdicts belong to this run.

The orchestration scores **1/1/0/1/2 = 5, involved**: the pristine run precedes mutant
execution, exact identities and failure predicates are checked, each process owns
bounded source snapshots, and the existing process owner coordinates failures. For S
source bytes across F files, T unique targets and D defects, source copying and
validation take O((D + 1)S) work, plus the native test work. With W active mutant
workers, private source storage is O(WS); the shared baseline retains O(F + T) hashes
and target names. No function bodies or import state are restored between tests because
each mutant interpreter exits.

These checks run inside `mise formal-conformance` and the full `mise formal`. Run only
these checks with `mise formal-defects`. They demonstrate sensitivity to these twenty
regressions, not that all possible defects will be detected. When implementation
structure changes, update the mutation location while retaining the violated behavioral
contract and independent failing check.
