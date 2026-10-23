# Cumulative fire activity

`FireActivity.lean` defines the growth policy used by `fires.activity.growth_window`
and `active_status`. `OracleActivity.lean` executes those same definitions. The policy
was proved before its Python implementation was written. Build it with `mise
formal-lean`, then run `mise formal-conformance` to check the implementation bridge.

The reference accepts source activity plus two independent raw acreage histories:
reported acreage and measured full mapped footprints. An observation contains signed
elapsed seconds and exact nonnegative integer acres. The reference instant is explicit.
Future observations are removed first. At equal timestamps, the last source occurrence
wins. Baselines use the greatest timestamp at or before each window cutoff, independent
of source order. Growth is the greatest subsequent area minus that baseline, floored at
zero. A decline and rebound therefore do not accumulate twice.

The three-day trigger requires growth strictly greater than ten acres and half a
percent of its baseline. The seven-day trigger requires growth strictly greater than
ten acres, plus either twenty-five acres or one percent of its own baseline. Integer
cross multiplication expresses the percentage boundaries exactly. Either history may
supply a trigger. Acreages from different histories are never compared with each other.

Source inactivity has priority. A source-active fire with no past dated acreage in
either stream stays Active. A nonempty stream lacking a three-day baseline supplies
initial grace. Missing a seven-day baseline supplies no additional grace. Old evidence
needs no refresh: once its window has no subsequent increase, its growth is zero and
the fire may become Holding. The model has no observation-age gate.

The proofs establish:

- Baseline source membership, past eligibility, and maximal eligible timestamp.
- Last-sample selection for equal-time corrections.
- Future-append invariance for complete window, stream, and status calculations.
- Source inactivity priority and Active classification for completely unknown history.
- Initial short-window grace and the absence of a separate long-window grace period.
- Strict thresholds and independent long-window area and percentage admission routes.
- Zero window growth when no later eligible observation follows a known baseline.

The conformance bridge checks 1,219 raw histories through both windows and both stream
positions with both source statuses: 2,438 window results and 4,876 status results.
The histories vary timestamp ordering, future evidence, both cutoff equalities,
same-time corrections, absent and zero baselines, decline/rebound peaks, and strict
acreage and percentage boundaries. Four two-stream cases check independent bases and
either-stream admission. Equivalent square-meter input checks the real unit adapter
away from threshold boundaries.

The ideal proofs do not establish binary floating-point accuracy, geometry area
measurement, source-clock truth, canonical report reconciliation, or external source
accuracy. The mapped adapter's aggregation of simultaneous footprints happens before
this pure policy and has separate production tests. Selecting the threshold values is
a product judgment; the proof establishes their specified effect rather than their
empirical quality. The data analysis used to choose them is retrospective and is not a
held-out validation set.
