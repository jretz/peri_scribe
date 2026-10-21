--------------------- MODULE ParallelSourceAuthentication ---------------------
EXTENDS Naturals, Sequences, FiniteSets

\* Each source represents an independent strided worker batch. Hashing is atomic
\* with a reliable pre/post identity check; explicit read failures include a
\* detected identity change during that read. Later edits can race admission.
Paths == 1..2
VARIABLES stamps, workers, captured, cancelled, active, sameProcess, joined,
          phase, pending
variables == <<stamps, workers, captured, cancelled, active, sameProcess, joined,
               phase, pending>>
Empty == <<0, 0>>

Init ==
    /\ stamps = <<1, 1>> /\ workers = Empty /\ captured = Empty
    /\ cancelled = FALSE /\ active = TRUE /\ sameProcess = TRUE
    /\ joined = FALSE /\ phase = "reading" /\ pending = Empty

Read(path) ==
    /\ phase = "reading" /\ workers[path] = 0 /\ ~cancelled
    /\ ~\E other \in Paths: workers[other] = 2
    /\ workers' = [workers EXCEPT ![path] = 1]
    /\ captured' = [captured EXCEPT ![path] = stamps[path]]
    /\ UNCHANGED <<stamps, cancelled, active, sameProcess, joined, phase, pending>>

Fail(path) ==
    /\ phase = "reading" /\ workers[path] = 0
    /\ workers' = [workers EXCEPT ![path] = 2]
    /\ UNCHANGED <<stamps, captured, cancelled, active, sameProcess, joined,
                    phase, pending>>

Cancel ==
    /\ phase = "reading" /\ ~cancelled /\ cancelled' = TRUE
    /\ UNCHANGED <<stamps, workers, captured, active, sameProcess, joined,
                    phase, pending>>

Stop(path) ==
    /\ phase = "reading" /\ workers[path] = 0
    /\ cancelled \/ (\E other \in Paths: workers[other] = 2)
    /\ workers' = [workers EXCEPT ![path] = 3]
    /\ UNCHANGED <<stamps, captured, cancelled, active, sameProcess, joined,
                    phase, pending>>

Edit(path) ==
    /\ phase \in {"reading", "joined"} /\ stamps[path] = 1
    /\ stamps' = [stamps EXCEPT ![path] = 2]
    /\ UNCHANGED <<workers, captured, cancelled, active, sameProcess, joined,
                    phase, pending>>

Expire ==
    /\ phase \in {"reading", "joined"} /\ active /\ active' = FALSE
    /\ UNCHANGED <<stamps, workers, captured, cancelled, sameProcess, joined,
                    phase, pending>>

Fork ==
    /\ phase \in {"reading", "joined"} /\ sameProcess
    /\ sameProcess' = FALSE
    /\ UNCHANGED <<stamps, workers, captured, cancelled, active, joined,
                    phase, pending>>

Join ==
    /\ phase = "reading" /\ \A path \in Paths: workers[path] # 0
    /\ joined' = TRUE /\ phase' = "joined"
    /\ UNCHANGED <<stamps, workers, captured, cancelled, active, sameProcess,
                    pending>>

Eligible == active /\ sameProcess /\ ~cancelled
            /\ (\A path \in Paths: workers[path] = 1)
            /\ captured = stamps

Resolve ==
    /\ phase = "joined"
    /\ phase' = IF Eligible THEN "published" ELSE "aborted"
    /\ pending' = IF Eligible THEN captured ELSE Empty
    /\ UNCHANGED <<stamps, workers, captured, cancelled, active, sameProcess,
                    joined>>

Cleanup ==
    /\ phase \in {"published", "aborted"}
    /\ phase' = "cleaned" /\ pending' = Empty /\ active' = FALSE
    /\ UNCHANGED <<stamps, workers, captured, cancelled, sameProcess, joined>>

Next == (\E path \in Paths: Read(path) \/ Fail(path) \/ Stop(path) \/ Edit(path))
        \/ Cancel \/ Expire \/ Fork \/ Join \/ Resolve \/ Cleanup
Spec == Init /\ [][Next]_variables

NoWorkerPublication == phase \in {"reading", "joined"} => pending = Empty
NoPartialPublication == pending = Empty \/ (\A path \in Paths: pending[path] > 0)
PublicationAfterJoin == pending # Empty => joined
PublishedEvidenceIsCurrent == phase = "published" =>
    active /\ sameProcess /\ ~cancelled /\ pending = stamps
FailureCannotPublish == (\E path \in Paths: workers[path] # 1) => pending = Empty
CleanupAfterJoin == phase = "cleaned" => joined
=============================================================================
