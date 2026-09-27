----------------------------- MODULE ParsedCache -----------------------------
EXTENDS Naturals, Sequences

VARIABLES initial, target, durable, pending, serial, statement, completed,
          failed, phase
variables == <<initial, target, durable, pending, serial, statement, completed,
               failed, phase>>

Complete(value) == [receipt |-> value, rows |-> value, memberships |-> value]
Empty == Complete(0)
Initials == {<<1, 1>>, <<1, 0>>, <<0, 0>>}
Targets == {<<2, 1>>, <<1, 2>>, <<0, 2>>, <<0, 0>>}
Init ==
    /\ initial \in Initials /\ target \in Targets
    /\ durable = [i \in 1..2 |-> Complete(initial[i])]
    /\ pending = durable /\ serial = 1 /\ statement = 0 /\ completed = 0
    /\ failed = FALSE /\ phase = "writing"

StatementCount == IF target[serial] = 0 THEN 3 ELSE 5
Write ==
    /\ phase = "writing" /\ serial <= 2
    /\ initial[serial] # target[serial] /\ statement < StatementCount
    /\ pending' = [pending EXCEPT ![serial] =
        IF target[serial] = 0
        THEN CASE statement = 0 -> [@ EXCEPT !.rows = 0]
               [] statement = 1 -> [@ EXCEPT !.memberships = 0]
               [] OTHER -> Empty
        ELSE CASE statement = 0 -> [@ EXCEPT !.receipt = target[serial]]
               [] statement = 1 -> [@ EXCEPT !.rows = 0]
               [] statement = 2 -> [@ EXCEPT !.memberships = 0]
               [] statement = 3 -> [@ EXCEPT !.rows = target[serial]]
               [] OTHER -> [@ EXCEPT !.memberships = target[serial]]]
    /\ statement' = statement + 1 /\ completed' = completed + 1
    /\ UNCHANGED <<initial, target, durable, serial, failed, phase>>
Advance ==
    /\ phase = "writing" /\ serial <= 2
    /\ initial[serial] = target[serial] \/ statement = StatementCount
    /\ serial' = serial + 1 /\ statement' = 0
    /\ UNCHANGED <<initial, target, durable, pending, completed, failed, phase>>
Commit ==
    /\ phase = "writing" /\ serial = 3
    /\ durable' = pending /\ phase' = "committed"
    /\ UNCHANGED <<initial, target, pending, serial, statement, completed, failed>>
Abort ==
    /\ phase = "writing"
    /\ pending' = durable /\ phase' = "aborted" /\ failed' = TRUE
    /\ UNCHANGED <<initial, target, durable, serial, statement, completed>>
Restart ==
    /\ phase = "aborted"
    /\ pending' = durable /\ serial' = 1 /\ statement' = 0 /\ completed' = 0
    /\ failed' = FALSE /\ phase' = "writing"
    /\ UNCHANGED <<initial, target, durable>>
Next == Write \/ Advance \/ Commit \/ Abort \/ Restart
Spec == Init /\ [][Next]_variables
DurableReceiptMatchesContents ==
    \A i \in 1..2: durable[i] = Complete(durable[i].receipt)
CommitMatchesInventory ==
    phase = "committed" => \A i \in 1..2: durable[i] = Complete(target[i])
FailurePreservesCommittedData ==
    failed => \A i \in 1..2: durable[i] = Complete(initial[i])
=============================================================================
