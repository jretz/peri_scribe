----------------------------- MODULE FetchCrash -----------------------------
EXTENDS PipelineState

CONSTANT MaxCrashes

\* The fire snapshot and evacuation cache are independently durable mutations.
VARIABLES source, output, targets, pending, previous, phase, crashes, full,
          fireChanged, evacuationChanged, unconditional, proceed, action
variables == <<source, output, targets, pending, previous, phase, crashes, full,
               fireChanged, evacuationChanged, unconditional, proceed, action>>

Init ==
    /\ source = <<0, 0>>
    /\ output = source
    /\ targets \in [1..2 -> 0..1]
    /\ pending \in States
    /\ previous = pending
    /\ full \in BOOLEAN
    /\ unconditional \in BOOLEAN
    /\ fireChanged = FALSE
    /\ evacuationChanged = FALSE
    /\ proceed = FALSE
    /\ phase = "capture"
    /\ crashes = 0
    /\ action = "init"

Capture ==
    /\ phase = "capture"
    /\ previous' = pending
    /\ phase' = "mark"
    /\ action' = "capture"
    /\ UNCHANGED <<source, output, targets, pending, crashes, full,
                   fireChanged, evacuationChanged, unconditional, proceed>>

Mark ==
    /\ phase = "mark"
    /\ pending' = Require(pending, DerivedStages, FALSE)
    /\ phase' = "fullMarker"
    /\ action' = "mark"
    /\ UNCHANGED <<source, output, targets, previous, crashes, full,
                   fireChanged, evacuationChanged, unconditional, proceed>>

\* Scheduled-full collection separately persists its unconditional requirement.
FullMarker ==
    /\ phase = "fullMarker"
    /\ pending' = IF full THEN Require(pending, DerivedStages, TRUE) ELSE pending
    /\ phase' = "fire"
    /\ action' = "fullMarker"
    /\ UNCHANGED <<source, output, targets, previous, crashes, full,
                   fireChanged, evacuationChanged, unconditional, proceed>>

FetchFire ==
    /\ phase = "fire"
    /\ source' = [source EXCEPT ![1] = targets[1]]
    /\ fireChanged' = (source[1] # targets[1])
    /\ phase' = "evacuations"
    /\ action' = "fire"
    /\ UNCHANGED <<output, targets, pending, previous, crashes, full,
                   evacuationChanged, unconditional, proceed>>

FetchEvacuations ==
    /\ phase = "evacuations"
    /\ source' = [source EXCEPT ![2] = targets[2]]
    /\ evacuationChanged' = (source[2] # targets[2])
    /\ phase' = "settle"
    /\ action' = "evacuations"
    /\ UNCHANGED <<output, targets, pending, previous, crashes, full,
                   fireChanged, unconditional, proceed>>

\* A successful unchanged incremental fetch restores exactly its captured marker.
FinishFetch ==
    /\ phase = "settle"
    /\ pending' = IF ~fireChanged /\ ~evacuationChanged /\ ~full
                   THEN previous ELSE pending
    /\ proceed' = (Len(pending'.remaining) > 0 \/ unconditional)
    /\ phase' = IF proceed' THEN "derive" ELSE "done"
    /\ action' = "finish"
    /\ UNCHANGED <<source, output, targets, previous, crashes, full,
                   fireChanged, evacuationChanged, unconditional>>

\* A later invocation may observe unchanged inputs after either durable mutation.
Crash ==
    /\ phase \in {"capture", "mark", "fullMarker", "fire", "evacuations",
                   "settle", "derive"}
    /\ crashes < MaxCrashes
    /\ crashes' = crashes + 1
    /\ phase' = "retry"
    /\ action' = "crash"
    /\ UNCHANGED <<source, output, targets, pending, previous, full,
                   fireChanged, evacuationChanged, unconditional, proceed>>

Retry ==
    /\ phase = "retry"
    /\ phase' = "capture"
    /\ full' = FALSE
    /\ fireChanged' = FALSE
    /\ evacuationChanged' = FALSE
    /\ proceed' = FALSE
    /\ action' = "retry"
    /\ UNCHANGED <<source, output, targets, pending, previous, crashes, unconditional>>

\* RunScheduler separately checks per-stage execution and acknowledgment ordering.
Derive ==
    /\ phase = "derive"
    /\ output' = source
    /\ pending' = EmptyState
    /\ phase' = "done"
    /\ action' = "derive"
    /\ UNCHANGED <<source, targets, previous, crashes, full,
                   fireChanged, evacuationChanged, unconditional, proceed>>

Progress == Capture \/ Mark \/ FullMarker \/ FetchFire \/ FetchEvacuations \/
            FinishFetch \/ Retry \/ Derive
Next == Progress \/ Crash
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Progress)

TypeOK ==
    /\ source \in [1..2 -> 0..1] /\ output \in [1..2 -> 0..1]
    /\ targets \in [1..2 -> 0..1]
    /\ pending \in States /\ previous \in States
    /\ crashes \in 0..MaxCrashes
    /\ full \in BOOLEAN /\ unconditional \in BOOLEAN /\ proceed \in BOOLEAN
    /\ fireChanged \in BOOLEAN /\ evacuationChanged \in BOOLEAN
    /\ phase \in {"capture", "mark", "fullMarker", "fire", "evacuations",
                   "settle", "derive", "retry", "done"}
    /\ action \in {"init", "capture", "mark", "fullMarker", "fire", "evacuations",
                    "finish", "crash", "retry", "derive"}
PriorRequirementsPreserved ==
    phase # "done" =>
        /\ Members(previous.remaining) \subseteq Members(pending.remaining)
        /\ (previous.unconditional => pending.unconditional)
MutationProtected == source # output => pending.remaining = StageOrder
LostRebuildIsImpossible == phase = "done" => output = source
MarkerDoesNotForce == action = "mark" => pending.unconditional = previous.unconditional
UnchangedRestoresExactly ==
    action = "finish" /\ ~fireChanged /\ ~evacuationChanged /\ ~full =>
        pending = previous
ScheduledFullForcesRebuild ==
    full /\ phase \in {"fire", "evacuations", "settle", "derive"} =>
        pending.unconditional /\ pending.remaining = StageOrder
NoChangeSkip ==
    action = "finish" /\ ~fireChanged /\ ~evacuationChanged /\ ~full =>
        (proceed <=> Len(previous.remaining) > 0 \/ unconditional)
EventualCompletion == <> (phase = "done" /\ output = targets)
=============================================================================
