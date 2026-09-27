---------------------------- MODULE RunScheduler ----------------------------
EXTENDS PipelineState

CONSTANTS WriterCount, MaximumFailures, FullRunsOnly
Writers == 1..WriterCount
Phases == {"idle", "require", "execute", "acknowledge", "release"}

VARIABLES state, owner, phase, first, last, current, force, succeeded, failures
variables == <<state, owner, phase, first, last, current, force, succeeded,
               failures>>

Init ==
    /\ state = InvalidState
    /\ owner = 0
    /\ phase = [writer \in Writers |-> "idle"]
    /\ first = [writer \in Writers |-> 1]
    /\ last = [writer \in Writers |-> 4]
    /\ current = [writer \in Writers |-> 1]
    /\ force = [writer \in Writers |-> FALSE]
    /\ succeeded = [writer \in Writers |-> {}]
    /\ failures = MaximumFailures

Acquire(writer, start, finish, forced) ==
    /\ owner = 0
    /\ phase[writer] = "idle"
    /\ start <= finish
    /\ FullRunsOnly => start = 1 /\ finish = 4
    /\ owner' = writer
    /\ phase' = [phase EXCEPT ![writer] = "require"]
    /\ first' = [first EXCEPT ![writer] = start]
    /\ last' = [last EXCEPT ![writer] = finish]
    /\ current' = [current EXCEPT ![writer] = start]
    /\ force' = [force EXCEPT ![writer] = forced]
    /\ UNCHANGED <<state, succeeded, failures>>

\* These invocations start at a derived stage, so run records selected work first.
RequireSelected(writer) ==
    /\ owner = writer
    /\ phase[writer] = "require"
    /\ state' = Require(state, first[writer]..last[writer], force[writer])
    /\ phase' = [phase EXCEPT ![writer] = "execute"]
    /\ UNCHANGED <<owner, first, last, current, force, succeeded, failures>>

StageReturned(writer) ==
    /\ owner = writer
    /\ phase[writer] = "execute"
    /\ succeeded' = [succeeded EXCEPT ![writer] = @ \cup {current[writer]}]
    /\ phase' = [phase EXCEPT ![writer] = "acknowledge"]
    /\ UNCHANGED <<state, owner, first, last, current, force, failures>>

\* An output may already exist when an interruption prevents marker replacement.
Acknowledge(writer) ==
    /\ owner = writer
    /\ phase[writer] = "acknowledge"
    /\ state' = Complete(state, current[writer])
    /\ phase' = [phase EXCEPT ![writer] =
            IF current[writer] = last[writer] THEN "release" ELSE "execute"]
    /\ current' = [current EXCEPT ![writer] =
            IF @ = last[writer] THEN @ ELSE @ + 1]
    /\ UNCHANGED <<owner, first, last, force, succeeded, failures>>

Release(writer) ==
    /\ owner = writer
    /\ phase[writer] = "release"
    /\ owner' = 0
    /\ phase' = [phase EXCEPT ![writer] = "idle"]
    /\ first' = [first EXCEPT ![writer] = 1]
    /\ last' = [last EXCEPT ![writer] = 4]
    /\ current' = [current EXCEPT ![writer] = 1]
    /\ force' = [force EXCEPT ![writer] = FALSE]
    /\ succeeded' = [succeeded EXCEPT ![writer] = {}]
    /\ UNCHANGED <<state, failures>>

Crash(writer) ==
    /\ owner = writer
    /\ failures > 0
    /\ owner' = 0
    /\ phase' = [phase EXCEPT ![writer] = "idle"]
    /\ first' = [first EXCEPT ![writer] = 1]
    /\ last' = [last EXCEPT ![writer] = 4]
    /\ current' = [current EXCEPT ![writer] = 1]
    /\ force' = [force EXCEPT ![writer] = FALSE]
    /\ succeeded' = [succeeded EXCEPT ![writer] = {}]
    /\ failures' = failures - 1
    /\ UNCHANGED state

Progress ==
    \/ \E writer \in Writers, start \in DerivedStages,
          finish \in DerivedStages, forced \in BOOLEAN:
           Acquire(writer, start, finish, forced)
    \/ \E writer \in Writers:
           RequireSelected(writer) \/ StageReturned(writer)
           \/ Acknowledge(writer) \/ Release(writer)

Next == Progress \/ (\E writer \in Writers: Crash(writer))
Spec == Init /\ [][Next]_variables
FairSpec == Spec /\ WF_variables(Progress)

TypeOK ==
    /\ state \in States
    /\ owner \in 0..WriterCount
    /\ phase \in [Writers -> Phases]
    /\ first \in [Writers -> DerivedStages]
    /\ last \in [Writers -> DerivedStages]
    /\ current \in [Writers -> DerivedStages]
    /\ force \in [Writers -> BOOLEAN]
    /\ succeeded \in [Writers -> SUBSET DerivedStages]
    /\ failures \in 0..MaximumFailures

OneWriter == {writer \in Writers: phase[writer] # "idle"} =
                IF owner = 0 THEN {} ELSE {owner}
SelectionRespected ==
    \A writer \in Writers:
        first[writer] <= current[writer] /\ current[writer] <= last[writer]
AcknowledgmentFollowsSuccess ==
    \A writer \in Writers:
        phase[writer] = "acknowledge" => current[writer] \in succeeded[writer]
ExecutionIsOrdered ==
    \A writer \in Writers:
        phase[writer] # "idle" =>
            first[writer]..(current[writer] - 1) \subseteq succeeded[writer]
EventuallyRecovered == <> (state = EmptyState)
=============================================================================
