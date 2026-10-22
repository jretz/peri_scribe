# Ordered completion workers

`OrderedWorkers.tla` covers `peri_scribe.concurrency.ordered_parallel_map` and its
`ordered_results` iterator. Admission assigns consecutive positions, futures may start
and finish in any order, and observation retires pending weight. Successful delivery
requires the next original position. A known failure prevents later admission; its
exception waits behind all earlier input positions. Consumer closure cancels queued
work and resource release waits for running work to finish.

The safety configuration uses three tasks, two pending slots, two workers, a weight
budget of two, every combination of weights zero/one/three and every failure subset.
The oversized item can enter only an empty pending set. Invariants cover pending count,
admitted weight, worker count, successful ordered output, first-input failure, worker
join and successful-stage publication. Temporal safety properties prohibit admission
after an observed failure and delivery after closure.

The liveness configuration assumes weak fairness for admission, worker start/finish,
observation, delivery/error processing, cancellation of queued work and release.
These assumptions correspond to a terminating finite input, workers that eventually
return and a consumer that continues the iterator or closes the context. There is no
deadline or guarantee for a hung native call. Process termination, interrupted Python
thread joins and output-spool recovery are outside this model.

`tests/formal/conformance/test_ordered_workers.py` follows complete checked graph paths
for every initial weight/failure configuration, all six completion priority orders,
and consumption through completion or closure after zero/one results. Real Future
objects expose states and exceptions; only executor execution timing is controlled.
The production scheduler alone chooses submissions, waits and result retrieval.
Ordinary real-thread tests cover concurrent resource settlement and refill.

Source/weight/submit exceptions are coordinator aborts, represented by consumer
cancellation for cleanup; their exception text/type is outside this model. Task output
bytes and native allocation are also outside it. Pending weights are encoded resource
estimates, not RSS. Existing geography models govern the actual artifact publication
and authentication boundary; the model's `Publish` action is that successful-stage
connection rather than a new scheduler write.
