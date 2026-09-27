------------------------------ MODULE RunState ------------------------------
EXTENDS PipelineState

\* Event fields let the Python conformance test replay every checked transition.
VARIABLES before, after, operation, required, forced, completed
variables == <<before, after, operation, required, forced, completed>>

Init ==
    /\ before \in States
    /\ after = before
    /\ operation = "init"
    /\ required = {}
    /\ forced = FALSE
    /\ completed = 0

RequireAction(stages, force) ==
    /\ before' = after
    /\ after' = Require(after, stages, force)
    /\ operation' = "require"
    /\ required' = stages
    /\ forced' = force
    /\ completed' = 0

CompleteAction(stage) ==
    /\ before' = after
    /\ after' = Complete(after, stage)
    /\ operation' = "complete"
    /\ required' = {}
    /\ forced' = FALSE
    /\ completed' = stage

InvalidRead ==
    /\ before' = after
    /\ after' = InvalidState
    /\ operation' = "invalid"
    /\ required' = {}
    /\ forced' = FALSE
    /\ completed' = 0

Next ==
    \/ \E stages \in SUBSET DerivedStages, force \in BOOLEAN:
           RequireAction(stages, force)
    \/ \E stage \in 0..4: CompleteAction(stage)
    \/ InvalidRead

Spec == Init /\ [][Next]_variables

TypeOK ==
    /\ before \in States
    /\ after \in States
    /\ operation \in {"init", "require", "complete", "invalid"}
    /\ required \subseteq DerivedStages
    /\ forced \in BOOLEAN
    /\ completed \in 0..4

RequirementsAccumulate ==
    operation = "require" =>
        /\ Members(before.remaining) \cup required = Members(after.remaining)
        /\ after.unconditional = (before.unconditional \/ forced)

OnlyEarliestCompletes ==
    operation = "complete" =>
        IF Len(before.remaining) = 0 THEN after = before
        ELSE IF completed # Head(before.remaining) THEN after = before
        ELSE /\ Members(after.remaining) = Members(before.remaining) \ {completed}
             /\ Len(after.remaining) = Len(before.remaining) - 1
             /\ after.unconditional =
                    (before.unconditional /\ Len(after.remaining) > 0)

InvalidStateRequiresEverything == operation = "invalid" => after = InvalidState
=============================================================================
