-------------------------- MODULE SnapshotCollection ---------------------------
EXTENDS Naturals, FiniteSets

Objects == 1..2
Empty == [object \in Objects |-> 0]
Stored == [object \in Objects |-> IF object = 1 THEN 1 ELSE 0]
Present(rows) == {object \in Objects: rows[object] # 0}
Merge(old, new) ==
    [object \in Objects |-> IF new[object] = 0 THEN old[object] ELSE new[object]]
VARIABLES remote, eligible, marker, mutated, full, phase, observedMarker,
          changed, listed, selected, response, atBody, saved, receipt, recoveryBase,
                   settled, recovery
variables == <<remote, eligible, marker, mutated, full, phase, observedMarker,
               changed, listed, selected, response, atBody, saved, receipt,
               recoveryBase, settled, recovery>>
Init ==
    /\ remote \in [Objects -> 0..1] /\ remote[1] = 1
    /\ eligible \in SUBSET Present(remote) /\ marker \in {1, 2}
    /\ mutated = FALSE /\ full \in BOOLEAN /\ phase = "metadata"
    /\ observedMarker = 0 /\ changed = {} /\ listed = {} /\ selected = {}
    /\ response = Empty /\ atBody = Empty /\ saved = Stored /\ receipt = 1
    /\ recoveryBase = Stored /\ settled = FALSE /\ recovery = FALSE
\* Mutations may change IDs, data, and timestamp eligibility independently.
Settle ==
    /\ ~settled /\ settled' = TRUE
    /\ UNCHANGED <<remote, eligible, marker, mutated, full, phase, observedMarker,
                   changed, listed, selected, response, atBody, saved, receipt,
                   recoveryBase, recovery>>
Mutate ==
    /\ ~mutated /\ ~settled
    /\ remote' \in [Objects -> 0..2] /\ Present(remote') # {}
    /\ eligible' \in SUBSET Present(remote') /\ marker' \in {marker, 2}
    /\ mutated' = TRUE
    /\ UNCHANGED <<full, phase, observedMarker, changed, listed, selected,
                   response, atBody, saved, receipt, recoveryBase, settled, recovery>>
Metadata ==
    /\ phase = "metadata"
    /\ observedMarker' = marker
    /\ phase' = IF ~full /\ receipt = marker THEN "done"
                ELSE IF full THEN "body" ELSE "changed"
    /\ UNCHANGED <<remote, eligible, marker, mutated, full, changed, listed,
                   selected, response, atBody, saved, receipt, recoveryBase, settled,
                   recovery>>
ChangedIDs ==
    /\ phase = "changed" /\ changed' = eligible /\ phase' = "ids"
    /\ UNCHANGED <<remote, eligible, marker, mutated, full, observedMarker,
                   listed, selected, response, atBody, saved, receipt, recoveryBase,
                   settled, recovery>>
AllIDs ==
    /\ phase = "ids"
    /\ listed' = Present(remote)
    /\ selected' = changed \cup (Present(remote) \ Present(saved))
    /\ phase' = IF selected' = {} THEN "done" ELSE "body"
    /\ UNCHANGED <<remote, eligible, marker, mutated, full, observedMarker,
                   changed, response, atBody, saved, receipt, recoveryBase, settled,
                   recovery>>
Body ==
    /\ phase = "body" /\ atBody' = remote
    /\ response' = [object \in Objects |->
          IF full \/ object \in selected THEN remote[object] ELSE 0]
    /\ phase' = IF response' = Empty THEN "done" ELSE "persist"
    /\ UNCHANGED <<remote, eligible, marker, mutated, full, observedMarker,
                   changed, listed, selected, saved, receipt, recoveryBase, settled,
                   recovery>>
Persist ==
    /\ phase = "persist"
    /\ saved' = Merge(saved, response)
    /\ receipt' = IF saved' = saved THEN receipt ELSE observedMarker
    /\ phase' = "done"
    /\ UNCHANGED <<remote, eligible, marker, mutated, full, observedMarker,
                   changed, listed, selected, response, atBody, recoveryBase,
                   settled, recovery>>
\* A future full invocation begins after mutations stop, ignoring all receipts.
Recover ==
    /\ phase = "done" /\ settled /\ ~recovery
    /\ recovery' = TRUE /\ full' = TRUE /\ phase' = "metadata"
    /\ recoveryBase' = saved
    /\ changed' = {} /\ listed' = {} /\ selected' = {}
    /\ response' = Empty /\ atBody' = Empty
    /\ UNCHANGED <<remote, eligible, marker, mutated, observedMarker, saved, receipt,
                   settled>>
Next == Settle \/ Mutate \/ Metadata \/ ChangedIDs \/ AllIDs
        \/ Body \/ Persist \/ Recover
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Settle) /\ WF_variables(Metadata)
                 /\ WF_variables(ChangedIDs)
                 /\ WF_variables(AllIDs) /\ WF_variables(Body)
                 /\ WF_variables(Persist) /\ WF_variables(Recover)
TypeOK ==
    /\ remote \in [Objects -> 0..2] /\ saved \in [Objects -> 0..2]
    /\ response \in [Objects -> 0..2] /\ atBody \in [Objects -> 0..2]
    /\ recoveryBase \in [Objects -> 0..2]
    /\ eligible \subseteq Present(remote) /\ marker \in {1, 2}
    /\ observedMarker \in 0..2 /\ receipt \in {1, 2}
    /\ full \in BOOLEAN /\ mutated \in BOOLEAN /\ recovery \in BOOLEAN
    /\ settled \in BOOLEAN
    /\ changed \subseteq Objects /\ listed \subseteq Objects
    /\ selected \subseteq Objects
    /\ phase \in {"metadata", "changed", "ids", "body", "persist", "done"}
OnlyObservedRows == \A object \in Present(response):
    response[object] = atBody[object]
SelectionCoversQueries == ~full /\ phase \in {"body", "persist", "done"}
    /\ listed # {} => changed \cup (listed \ Present(Stored)) \subseteq selected
StoredRowsSurvive == 1 \in Present(saved)
StableFullIsComplete == recovery /\ phase = "done" =>
    \A object \in Present(remote): saved[object] = remote[object]
EventuallyComplete == <> (recovery /\ phase = "done")
=============================================================================
