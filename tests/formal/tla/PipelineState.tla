--------------------------- MODULE PipelineState ---------------------------
EXTENDS Naturals, Sequences, FiniteSets

\* Stage numbers preserve the order shared by CLI selection and recovery markers.
DerivedStages == 1..4
StageOrder == <<1, 2, 3, 4>>
Canonical(stages) == SelectSeq(StageOrder, LAMBDA stage: stage \in stages)
Members(sequence) == {sequence[index]: index \in DOMAIN sequence}
States == [remaining: {Canonical(stages): stages \in SUBSET DerivedStages},
           unconditional: BOOLEAN]
EmptyState == [remaining |-> <<>>, unconditional |-> FALSE]
InvalidState == [remaining |-> StageOrder, unconditional |-> TRUE]

Require(state, stages, force) ==
    [remaining |-> Canonical(Members(state.remaining) \cup stages),
     unconditional |-> state.unconditional \/ force]

Complete(state, stage) ==
    IF Len(state.remaining) = 0 THEN state
    ELSE IF Head(state.remaining) # stage THEN state
    ELSE [remaining |-> Tail(state.remaining),
          unconditional |-> state.unconditional /\ Len(state.remaining) > 1]
=============================================================================
