----------------------------- MODULE MonitorContext -----------------------------
EXTENDS Naturals, Sequences, FiniteSets

Record == [when: 0..3, run: 0..1, important: BOOLEAN]
Histories == {<<>>} \cup {<<item>>: item \in Record}
             \cup {<<first, second>>: first \in Record, second \in Record}
VARIABLES records, recent, restored, checked
variables == <<records, recent, restored, checked>>
RecentIndices == {index \in DOMAIN records: records[index].when >= 2}
SelectedRuns == {records[index].run: index \in RecentIndices}
Older(run) == {index \in DOMAIN records:
                  records[index].run = run /\ records[index].important /\
                  records[index].when < 2}
Init == /\ records \in Histories /\ recent = RecentIndices
        /\ restored = {} /\ checked = {}
Restore(run) ==
    /\ run \in SelectedRuns \ checked
    /\ checked' = checked \cup {run}
    /\ restored' = restored \cup Older(run)
    /\ UNCHANGED <<records, recent>>
Next == \E run \in 0..1: Restore(run)
Spec == Init /\ [][Next]_variables
FairSpec == Spec /\ WF_variables(Next)
NoDuplicateContext == recent \intersect restored = {}
OnlySelectedContext == \A index \in restored:
    records[index].run \in SelectedRuns /\ records[index].important
AllCheckedContextPresent == \A run \in checked: Older(run) \subseteq restored
ContextComplete == <>(checked = SelectedRuns)
=============================================================================
