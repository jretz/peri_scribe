----------------------------- MODULE MonitorReader -----------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANT MaximumSteps
VARIABLES files, positions, known, current, nextRecord, partial, delivered,
          expected, trace, awaitingReset
variables == <<files, positions, known, current, nextRecord, partial, delivered,
               expected, trace, awaitingReset>>
Init == /\ files = [index \in 0..1 |-> <<>>]
        /\ positions = [index \in 0..1 |-> 0]
        /\ known = {0} /\ current = 0 /\ nextRecord = 1 /\ partial = FALSE
        /\ delivered = <<>> /\ expected = {} /\ trace = <<>>
        /\ awaitingReset = FALSE
CanStep == Len(trace) < MaximumSteps
Write ==
    /\ CanStep /\ ~awaitingReset /\ ~partial /\ nextRecord <= 3
    /\ files' = [files EXCEPT ![current] = Append(@, nextRecord)]
    /\ expected' = expected \cup {nextRecord} /\ nextRecord' = nextRecord + 1
    /\ trace' = Append(trace, "write")
    /\ UNCHANGED <<positions, known, current, partial, delivered, awaitingReset>>
StartPartial ==
    /\ CanStep /\ ~awaitingReset /\ ~partial /\ nextRecord <= 3
    /\ partial' = TRUE
    /\ trace' = Append(trace, "partial")
    /\ UNCHANGED <<files, positions, known, current, nextRecord, delivered, expected,
                   awaitingReset>>
FinishPartial ==
    /\ CanStep /\ partial /\ partial' = FALSE
    /\ files' = [files EXCEPT ![current] = Append(@, nextRecord)]
    /\ expected' = expected \cup {nextRecord} /\ nextRecord' = nextRecord + 1
    /\ trace' = Append(trace, "finish")
    /\ UNCHANGED <<positions, known, current, delivered, awaitingReset>>
Unread(index) == IF index \in known
                THEN SubSeq(files[index], positions[index] + 1, Len(files[index]))
                ELSE <<>>
Poll ==
    /\ CanStep
    /\ delivered' = delivered \o Unread(0) \o Unread(1)
    /\ positions' = [index \in 0..1 |-> Len(files[index])]
    /\ known' = {current} /\ trace' = Append(trace, "poll")
    /\ awaitingReset' = FALSE
    /\ UNCHANGED <<files, current, nextRecord, partial, expected>>
Rotate ==
    /\ CanStep /\ ~awaitingReset /\ current = 0 /\ ~partial
    /\ current' = 1 /\ known' = known \cup {1}
    /\ trace' = Append(trace, "rotate")
    /\ UNCHANGED <<files, positions, nextRecord, partial, delivered, expected,
                   awaitingReset>>
Truncate ==
    /\ CanStep /\ partial /\ positions[current] = Len(files[current])
    /\ files' = [files EXCEPT ![current] = <<>>]
    /\ positions' = [positions EXCEPT ![current] = 0]
    /\ partial' = FALSE /\ trace' = Append(trace, "truncate")
    /\ awaitingReset' = TRUE
    /\ UNCHANGED <<known, current, nextRecord, delivered, expected>>
Next == Write \/ StartPartial \/ FinishPartial \/ Poll \/ Rotate \/ Truncate
Spec == Init /\ [][Next]_variables
TypeOK == /\ delivered \in Seq(1..3) /\ current \in 0..1
          /\ partial \in BOOLEAN /\ nextRecord \in 1..4
          /\ \A index \in 0..1: positions[index] <= Len(files[index])
NoDuplicateDelivery == Cardinality({delivered[index]: index \in DOMAIN delivered})
                        = Len(delivered)
OnlyCompletedRecords ==
    {delivered[index]: index \in DOMAIN delivered} \subseteq expected
NoLossAfterPoll == Len(trace) > 0 /\ trace[Len(trace)] = "poll" =>
    {delivered[index]: index \in DOMAIN delivered} = expected
=============================================================================
