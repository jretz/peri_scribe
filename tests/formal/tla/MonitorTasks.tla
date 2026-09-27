--------------------------- MODULE MonitorTasks ---------------------------
EXTENDS Naturals, FiniteSets

CONSTANT Operations
VARIABLES phase, active, stopped, closed, writer, base, result, published,
          cancellations
variables == <<phase, active, stopped, closed, writer, base, result, published,
               cancellations>>
Busy == {"waiting", "reading", "ready", "settled"}

Init ==
    /\ phase = [operation \in Operations |-> "queued"]
    /\ active = 0 /\ stopped = FALSE /\ closed = FALSE
    /\ writer \in BOOLEAN
    /\ base = {} /\ result = {} /\ published = {}
    /\ cancellations = [operation \in Operations |-> 0]

Admit(operation) ==
    /\ ~stopped /\ active = 0 /\ phase[operation] = "queued"
    /\ active' = operation
    /\ phase' = [phase EXCEPT ![operation] = "waiting"]
    /\ base' = published /\ result' = published
    /\ UNCHANGED <<stopped, closed, writer, published, cancellations>>

Cancel(operation) ==
    /\ phase[operation] \in Busy \cup {"queued"}
    /\ cancellations[operation] < 2
    /\ cancellations' = [cancellations EXCEPT ![operation] = @ + 1]
    /\ phase' = IF phase[operation] = "queued"
                 THEN [phase EXCEPT ![operation] = "cancelled"] ELSE phase
    /\ UNCHANGED <<active, stopped, closed, writer, base, result, published>>

ReleaseWriter ==
    /\ writer /\ writer' = FALSE
    /\ UNCHANGED <<phase, active, stopped, closed, base, result, published,
                    cancellations>>

StartRead ==
    /\ active # 0 /\ phase[active] = "waiting" /\ ~writer
    /\ phase' = [phase EXCEPT ![active] = "reading"]
    /\ UNCHANGED <<active, stopped, closed, writer, base, result, published,
                    cancellations>>

FinishRead ==
    /\ active # 0 /\ phase[active] = "reading"
    /\ phase' = [phase EXCEPT ![active] = "ready"]
    /\ result' = base \cup {active}
    /\ UNCHANGED <<active, stopped, closed, writer, base, published, cancellations>>

Settle ==
    /\ active # 0 /\ phase[active] = "ready"
    /\ published' = IF stopped THEN published ELSE result
    /\ phase' = [phase EXCEPT ![active] = "settled"]
    /\ UNCHANGED <<active, stopped, closed, writer, base, result, cancellations>>

FailRead ==
    /\ active # 0 /\ phase[active] \in {"waiting", "reading", "ready"}
    /\ phase' = [phase EXCEPT ![active] = "settled"]
    /\ UNCHANGED <<active, stopped, closed, writer, base, result, published,
                    cancellations>>

Retire ==
    /\ active # 0 /\ phase[active] = "settled"
    /\ phase' = [phase EXCEPT ![active] = "done"] /\ active' = 0
    /\ UNCHANGED <<stopped, closed, writer, base, result, published, cancellations>>

Stop ==
    /\ ~stopped /\ stopped' = TRUE
    /\ phase' = [operation \in Operations |->
                    IF phase[operation] = "queued" THEN "cancelled"
                    ELSE phase[operation]]
    /\ UNCHANGED <<active, closed, writer, base, result, published, cancellations>>

Close ==
    /\ stopped /\ active = 0 /\ ~closed /\ closed' = TRUE
    /\ UNCHANGED <<phase, active, stopped, writer, base, result, published,
                    cancellations>>

Next == (\E operation \in Operations: Admit(operation) \/ Cancel(operation))
        \/ ReleaseWriter \/ StartRead \/ FinishRead \/ Settle \/ FailRead
        \/ Retire \/ Stop \/ Close
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(ReleaseWriter) /\ WF_variables(StartRead)
                 /\ WF_variables(FinishRead) /\ WF_variables(Settle)
                 /\ WF_variables(Retire) /\ WF_variables(Close)

TypeOK ==
    /\ phase \in [Operations -> Busy \cup {"queued", "done", "cancelled"}]
    /\ active \in Operations \cup {0}
    /\ stopped \in BOOLEAN /\ closed \in BOOLEAN /\ writer \in BOOLEAN
    /\ base \subseteq Operations /\ result \subseteq Operations
    /\ published \subseteq Operations
    /\ cancellations \in [Operations -> 0..2]
ExclusiveOwner == \A operation \in Operations:
                      phase[operation] \in Busy => active = operation
ResourcesRetained == active # 0 => ~closed
FreshPublication == active # 0 /\ phase[active] \in {"waiting", "reading", "ready"}
                    => base = published
ClosedAdmission == closed => stopped
NoPublicationAfterStop == [][stopped => published' = published]_variables
EvidencePreserved == [][published \subseteq published']_variables
EventuallyClosed == stopped ~> closed
=============================================================================
