---------------------------- MODULE WorkerLifetime ----------------------------
EXTENDS Naturals

VARIABLES worker, owner, permit, cancellations, stopped, outcome, fails,
          reads, delivered, reading
variables == <<worker, owner, permit, cancellations, stopped, outcome, fails,
               reads, delivered, reading>>
Init ==
    /\ worker = "running" /\ owner = "waiting" /\ permit = TRUE
    /\ cancellations = 0 /\ stopped = FALSE /\ outcome = "pending"
    /\ fails \in BOOLEAN /\ reads = 0 /\ delivered = 0 /\ reading = FALSE
Cancel ==
    /\ owner # "returned"
    /\ cancellations' = IF cancellations < 2 THEN cancellations + 1 ELSE 2
    /\ stopped' = TRUE /\ owner' = "cleanup"
    /\ UNCHANGED <<worker, permit, outcome, fails, reads, delivered, reading>>
StartRead ==
    /\ worker = "running" /\ ~stopped /\ ~reading /\ reads < 2
    /\ reads' = reads + 1 /\ reading' = TRUE
    /\ UNCHANGED <<worker, owner, permit, cancellations, stopped, outcome,
                   fails, delivered>>
FinishRead ==
    /\ reading /\ worker = "running"
    /\ reading' = FALSE
    /\ delivered' = IF stopped THEN delivered ELSE delivered + 1
    /\ UNCHANGED <<worker, owner, permit, cancellations, stopped, outcome,
                   fails, reads>>
WorkerExit ==
    /\ worker = "running" /\ ~reading
    /\ worker' = "exited"
    /\ UNCHANGED <<owner, permit, cancellations, stopped, outcome, fails,
                   reads, delivered, reading>>
Return ==
    /\ worker = "exited" /\ owner # "returned"
    /\ owner' = "returned" /\ permit' = FALSE
    /\ outcome' = IF cancellations > 0 THEN "cancelled"
                   ELSE IF fails THEN "error" ELSE "value"
    /\ UNCHANGED <<worker, cancellations, stopped, fails, reads, delivered, reading>>
Next == Cancel \/ StartRead \/ FinishRead \/ WorkerExit \/ Return
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(FinishRead) /\ WF_variables(WorkerExit)
                 /\ WF_variables(Return)
TypeOK ==
    /\ worker \in {"running", "exited"}
    /\ owner \in {"waiting", "cleanup", "returned"} /\ permit \in BOOLEAN
    /\ cancellations \in 0..2 /\ stopped \in BOOLEAN /\ fails \in BOOLEAN
    /\ reads \in 0..2 /\ delivered \in 0..2 /\ reading \in BOOLEAN
    /\ outcome \in {"pending", "cancelled", "error", "value"}
WorkerRetainsResources == worker = "running" => permit /\ owner # "returned"
CancelTakesPrecedence == owner = "returned" /\ cancellations > 0 =>
                            outcome = "cancelled"
DeliveredOnlyReadChunks == delivered <= reads
NoReadAfterStop == [][reads' > reads => ~stopped]_variables
NoDeliveryAfterStop == [][stopped => delivered' = delivered]_variables
EventuallyReleased == <> (~permit)
=============================================================================
