---------------------------- MODULE FeedCoordinator ----------------------------
EXTENDS Naturals, FiniteSets

CONSTANT FeedCount, Capacity
Feeds == 1..FeedCount
Kinds == {"change", "same", "sourceError", "fatalBefore", "fatalAfter"}
VARIABLES kind, worker, result, snapshots, indexed, phase, cancel, full, prior,
          pending, acknowledged, indexFailure, deferIndex, indexAttempted
variables == <<kind, worker, result, snapshots, indexed, phase, cancel, full,
               prior, pending, acknowledged, indexFailure, deferIndex, indexAttempted>>
Init ==
    /\ kind \in [Feeds -> Kinds]
    /\ worker = [feed \in Feeds |-> "waiting"]
    /\ result = [feed \in Feeds |-> "none"]
    /\ snapshots = {} /\ indexed = {} /\ phase = "mark" /\ cancel = FALSE
    /\ full \in BOOLEAN /\ prior \in BOOLEAN /\ pending = prior
    /\ acknowledged = FALSE /\ indexFailure \in BOOLEAN /\ deferIndex \in BOOLEAN
    /\ indexAttempted = FALSE
Mark ==
    /\ phase = "mark" /\ pending' = TRUE /\ phase' = "collect"
    /\ UNCHANGED <<kind, worker, result, snapshots, indexed, cancel, full, prior,
                   acknowledged, indexFailure, deferIndex, indexAttempted>>
Start(feed) ==
    /\ phase = "collect" /\ ~cancel /\ worker[feed] = "waiting"
    /\ Cardinality({other \in Feeds: worker[other] = "running"}) < Capacity
    /\ worker' = [worker EXCEPT ![feed] = "running"]
    /\ UNCHANGED <<kind, result, snapshots, indexed, phase, cancel, full, prior,
                   pending, acknowledged, indexFailure, deferIndex, indexAttempted>>
\* Thread cancellation does not stop an in-flight filesystem write.
Finish(feed) ==
    /\ phase = "collect" /\ worker[feed] = "running"
    /\ snapshots' = IF kind[feed] \in {"change", "fatalAfter"}
                    THEN snapshots \cup {feed} ELSE snapshots
    /\ worker' = [worker EXCEPT ![feed] = "finished"]
    /\ result' = [result EXCEPT ![feed] = IF cancel THEN "none"
         ELSE IF kind[feed] \in {"fatalBefore", "fatalAfter"} THEN "fatal"
         ELSE kind[feed]]
    /\ UNCHANGED <<kind, indexed, phase, cancel, full, prior, pending, acknowledged,
                   indexFailure, deferIndex, indexAttempted>>
Cancel ==
    /\ phase = "collect" /\ ~cancel
    /\ \E feed \in Feeds: result[feed] = "fatal"
    /\ cancel' = TRUE
    /\ worker' = [feed \in Feeds |->
          IF worker[feed] = "waiting" THEN "cancelled" ELSE worker[feed]]
    /\ UNCHANGED <<kind, result, snapshots, indexed, phase, full, prior, pending,
                   acknowledged, indexFailure, deferIndex, indexAttempted>>
Join ==
    /\ phase = "collect"
    /\ \A feed \in Feeds: worker[feed] \in {"finished", "cancelled"}
    /\ phase' = IF \E feed \in Feeds: result[feed] = "fatal" THEN "failed"
                ELSE "index"
    /\ UNCHANGED <<kind, worker, result, snapshots, indexed, cancel, full, prior,
                   pending, acknowledged, indexFailure, deferIndex, indexAttempted>>
Index ==
    /\ phase = "index"
    /\ indexAttempted' = (~deferIndex /\ (snapshots # {} \/ full))
    /\ indexed' = IF indexAttempted' /\ ~indexFailure THEN snapshots ELSE indexed
    /\ phase' = IF (indexAttempted' /\ indexFailure)
                   \/ (\E feed \in Feeds: result[feed] = "sourceError")
                THEN "failed" ELSE "ack"
    /\ UNCHANGED <<kind, worker, result, snapshots, cancel, full, prior, pending,
                   acknowledged, indexFailure, deferIndex>>
Ack ==
    /\ phase = "ack" /\ acknowledged' = (full /\ ~deferIndex)
    /\ phase' = "restore"
    /\ UNCHANGED <<kind, worker, result, snapshots, indexed, cancel, full, prior,
                   pending, indexFailure, deferIndex, indexAttempted>>
Restore ==
    /\ phase = "restore" /\ phase' = "done"
    /\ pending' = IF snapshots = {} /\ ~full /\ ~deferIndex THEN prior ELSE pending
    /\ UNCHANGED <<kind, worker, result, snapshots, indexed, cancel, full, prior,
                   acknowledged, indexFailure, deferIndex, indexAttempted>>
\* Process loss terminates all workers and cannot remove already persisted intent.
Crash ==
    /\ phase \notin {"done", "failed", "crashed"} /\ phase' = "crashed"
    /\ UNCHANGED <<kind, worker, result, snapshots, indexed, cancel, full, prior,
                   pending, acknowledged, indexFailure, deferIndex, indexAttempted>>
Next == Mark \/ Cancel \/ Join \/ Index \/ Ack \/ Restore \/ Crash
        \/ \E feed \in Feeds: Start(feed) \/ Finish(feed)
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Mark) /\ WF_variables(Cancel)
                 /\ WF_variables(Join) /\ WF_variables(Index)
                 /\ WF_variables(Ack) /\ WF_variables(Restore)
                 /\ \A feed \in Feeds:
                        WF_variables(Start(feed)) /\ WF_variables(Finish(feed))
TypeOK ==
    /\ kind \in [Feeds -> Kinds]
    /\ worker \in [Feeds -> {"waiting", "running", "finished", "cancelled"}]
    /\ result \in [Feeds -> {"none", "change", "same", "sourceError", "fatal"}]
    /\ snapshots \subseteq Feeds /\ indexed \subseteq Feeds
    /\ phase \in {"mark", "collect", "index", "ack", "restore", "done",
                   "failed", "crashed"}
    /\ cancel \in BOOLEAN /\ full \in BOOLEAN /\ prior \in BOOLEAN
    /\ pending \in BOOLEAN /\ acknowledged \in BOOLEAN
    /\ indexFailure \in BOOLEAN /\ deferIndex \in BOOLEAN
    /\ indexAttempted \in BOOLEAN
BoundedWorkers == Cardinality({feed \in Feeds: worker[feed] = "running"}) <= Capacity
PublishedInputsRetainIntent == snapshots # {} => pending
OnlyUnchangedSuccessRestores == ~pending /\ phase = "done" =>
    snapshots = {} /\ ~full /\ ~prior
CoordinatorWaitsForWorkers == phase \in {"index", "ack", "restore", "done", "failed"}
    => \A feed \in Feeds: worker[feed] \in {"finished", "cancelled"}
NoFalseFullAcknowledgment == acknowledged =>
    /\ full /\ ~deferIndex /\ indexAttempted /\ ~indexFailure
    /\ indexed = snapshots
    /\ \A feed \in Feeds: result[feed] \in {"change", "same"}
SuccessfulIndexIncludesEverySnapshot == indexAttempted /\ ~indexFailure =>
    indexed = snapshots
OrdinaryFailuresDoNotCancel == cancel => \E feed \in Feeds: result[feed] = "fatal"
NoHiddenFailure == phase = "done" =>
    \A feed \in Feeds: result[feed] \in {"change", "same"}
EventuallySettled == <> (phase \in {"done", "failed", "crashed"})
=============================================================================
