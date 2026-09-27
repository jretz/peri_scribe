------------------------- MODULE IdentityRecomputation -------------------------
EXTENDS Naturals, FiniteSets

CONSTANT FireCount, HistoryCount
Fires == 0..(FireCount - 1)
Existing == 0..(HistoryCount - 1)
Histories == 0..(HistoryCount + FireCount - 1)
Missing == HistoryCount + FireCount
Fresh(fire) == HistoryCount + fire

\* Each fire represents one disjoint group of current aliases. Their union of known
\* buckets is explicit. Fire order is the fixed mapped-time/identity priority.
Contenders(routes, history) == {fire \in Fires : history \in routes[fire]}
Winner(routes, history) ==
    IF Contenders(routes, history) = {} THEN Missing
    ELSE CHOOSE fire \in Contenders(routes, history) :
        \A other \in Contenders(routes, history) : other <= fire
Won(routes, fire) == {history \in Histories : Winner(routes, history) = fire}
Writer(routes, preferred, fire) ==
    IF preferred[fire] \in Won(routes, fire) THEN preferred[fire]
    ELSE IF Won(routes, fire) = {} THEN Fresh(fire)
    ELSE CHOOSE history \in Won(routes, fire) :
        \A other \in Won(routes, fire) : history <= other
Writers(routes, preferred) == [fire \in Fires |-> Writer(routes, preferred, fire)]
Owners(routes, previous, selected) == [history \in Histories |->
    IF history \in {selected[fire] : fire \in Fires} THEN history
    ELSE IF Winner(routes, history) = Missing THEN previous[history]
    ELSE selected[Winner(routes, history)]]

VARIABLES phase, lineage, preferred, owners, evidence, writers,
          savedOwners, savedWriters, originalEvidence
variables == <<phase, lineage, preferred, owners, evidence, writers,
               savedOwners, savedWriters, originalEvidence>>
Init ==
    /\ phase = "resolve"
    /\ lineage \in [Fires -> SUBSET Existing]
    /\ preferred \in [Fires -> Existing \cup {Missing}]
    /\ \E old \in [Existing -> Existing] :
        owners = [history \in Histories |->
            IF history \in Existing THEN old[history] ELSE history]
    /\ evidence = [history \in Histories |->
        IF history \in Existing THEN {0} ELSE {}]
    /\ originalEvidence = evidence
    /\ writers = [fire \in Fires |-> Missing]
    /\ savedWriters = writers /\ savedOwners = owners
Resolve ==
    /\ phase = "resolve"
    /\ writers' = Writers(lineage, preferred)
    /\ owners' = Owners(lineage, owners, writers')
    /\ savedWriters' = writers' /\ savedOwners' = owners'
    /\ phase' = "learn"
    /\ UNCHANGED <<lineage, preferred, evidence, originalEvidence>>
Learn ==
    /\ phase = "learn"
    /\ lineage' = [fire \in Fires |-> lineage[fire] \cup
        {history \in Histories : owners[history] = writers[fire]}]
    /\ preferred' = writers /\ phase' = "acknowledge"
    /\ UNCHANGED <<owners, evidence, writers, savedOwners, savedWriters,
                   originalEvidence>>
Acknowledge ==
    /\ phase = "acknowledge"
    /\ evidence' = [history \in Histories |-> evidence[history] \cup
        {fire \in Fires : writers[fire] = history}]
    /\ phase' = "retry"
    /\ UNCHANGED <<lineage, preferred, owners, writers, savedOwners, savedWriters,
                   originalEvidence>>
Recompute ==
    /\ phase = "retry"
    /\ writers' = Writers(lineage, preferred)
    /\ owners' = Owners(lineage, owners, writers')
    /\ phase' = "done"
    /\ UNCHANGED <<lineage, preferred, evidence, savedOwners, savedWriters,
                   originalEvidence>>
Next == Resolve \/ Learn \/ Acknowledge \/ Recompute
Spec == Init /\ [][Next]_variables
TypeOK ==
    /\ phase \in {"resolve", "learn", "acknowledge", "retry", "done"}
    /\ lineage \in [Fires -> SUBSET Histories]
    /\ preferred \in [Fires -> Histories \cup {Missing}]
    /\ owners \in [Histories -> Histories]
    /\ evidence \in [Histories -> SUBSET Fires]
    /\ writers \in [Fires -> Histories \cup {Missing}]
UniqueWriters == phase # "resolve" =>
    \A first, second \in Fires : writers[first] = writers[second] => first = second
WritersOwnTheirBucket == phase # "resolve" =>
    \A fire \in Fires : owners[writers[fire]] = writers[fire]
EvidencePreserved == \A history \in Histories :
    originalEvidence[history] \subseteq evidence[history]
RecomputationStable == phase = "done" =>
    writers = savedWriters /\ owners = savedOwners
RetryHasNoNovelMapping == phase = "done" =>
    \A fire \in Fires : \E history \in Histories :
        owners[history] = writers[fire] /\ fire \in evidence[history]
LearnedRoutesStable == phase = "done" =>
    \A fire \in Fires :
        {history \in Histories : owners[history] = writers[fire]} \subseteq lineage[fire]
=============================================================================
