------------------------- MODULE PipelineComposition -------------------------
EXTENDS PipelineState, Integers

CONSTANT ExploratoryInvocations, MaximumFailures
Absent == -1
Initial == [source |-> 0, outputs |-> [stage \in DerivedStages |-> 0],
            pending |-> EmptyState, deferred |-> FALSE,
            kmzVersion |-> 0, publicationVersion |-> 0, publication |-> 0]
VARIABLES durable, before, invocation, first, last, gated, forced, changed,
          threshold, current, phase, inputs, previous, deferredBefore,
          executed, stageForces, failures, failedAt, action
variables == <<durable, before, invocation, first, last, gated, forced, changed,
               threshold, current, phase, inputs, previous, deferredBefore,
               executed, stageForces, failures, failedAt, action>>

Init == /\ durable = Initial /\ before = Initial /\ invocation = 0
        /\ first = 0 /\ last = 4 /\ gated = FALSE /\ forced = FALSE
        /\ changed = FALSE /\ threshold = FALSE /\ current = 0
        /\ phase = "idle" /\ inputs = Absent /\ previous = EmptyState
        /\ deferredBefore = FALSE /\ executed = <<>> /\ stageForces = <<>>
        /\ failures = 0 /\ failedAt = "" /\ action = "init"

Begin(start, finish, gate, force, change, qualifies) ==
    /\ phase = "idle" /\ start <= finish
    /\ invocation < ExploratoryInvocations \/
        (start = 0 /\ finish = 4 /\ ~gate /\ ~force /\ ~change /\ ~qualifies)
    /\ invocation' = invocation + 1 /\ first' = start /\ last' = finish
    /\ gated' = gate /\ forced' = force
    /\ changed' = change /\ threshold' = qualifies /\ current' = start
    /\ before' = durable /\ phase' = "stage" /\ inputs' = Absent
    /\ previous' = durable.pending /\ deferredBefore' = durable.deferred
    /\ durable' = IF finish > 0 /\ (force \/ start > 0)
        THEN [durable EXCEPT !.pending = Require(@, (start..finish) \cap DerivedStages,
                                                force)] ELSE durable
    /\ executed' = <<>> /\ stageForces' = <<>> /\ failedAt' = ""
    /\ action' = "begin" /\ UNCHANGED failures

EffectiveForce == forced \/ (durable.pending.unconditional /\
                             current \in Members(durable.pending.remaining))
ValidPublication == durable.publicationVersion = durable.kmzVersion /\
                    durable.publication # Absent
SavedPending == durable.source # durable.publication
GateAccepts == ~ValidPublication \/ (SavedPending /\ threshold)

StartFetch ==
    /\ phase = "stage" /\ current = 0
    /\ previous' = durable.pending /\ deferredBefore' = durable.deferred
    /\ durable' = IF gated THEN [durable EXCEPT !.deferred = TRUE]
        ELSE [durable EXCEPT !.pending = Require(@, DerivedStages, FALSE)]
    /\ executed' = Append(executed, 0)
    /\ stageForces' = Append(stageForces, EffectiveForce)
    /\ phase' = IF gated THEN "fetch write" ELSE "fetch consume"
    /\ action' = "start fetch"
    /\ UNCHANGED <<before, invocation, first, last, gated, forced, changed, threshold,
                   current, inputs, failures, failedAt>>

ConsumeDeferred ==
    /\ phase = "fetch consume"
    /\ durable' = [durable EXCEPT !.deferred = FALSE]
    /\ phase' = IF gated THEN "acknowledge" ELSE "fetch write"
    /\ action' = "consume deferred"
    /\ UNCHANGED <<before, invocation, first, last, gated, forced, changed, threshold,
                   current, inputs, previous, deferredBefore, executed, stageForces,
                   failures, failedAt>>

Fetch ==
    /\ phase = "fetch write"
    /\ durable' = [durable EXCEPT !.source = IF changed THEN 1 ELSE @]
    /\ phase' = "fetch decide" /\ action' = "fetch"
    /\ UNCHANGED <<before, invocation, first, last, gated, forced, changed, threshold,
                   current, inputs, previous, deferredBefore, executed, stageForces,
                   failures, failedAt>>

FinishFetch ==
    /\ phase = "fetch decide"
    /\ LET proceed == IF gated
            THEN forced \/ Len(durable.pending.remaining) > 0 \/ GateAccepts
            ELSE changed \/ deferredBefore \/ forced \/ Len(previous.remaining) > 0
       IN /\ durable' = IF gated
                THEN IF proceed
                    THEN [durable EXCEPT !.pending = Require(@, DerivedStages, FALSE)]
                    ELSE IF ~SavedPending
                         THEN [durable EXCEPT !.deferred = FALSE] ELSE durable
                ELSE IF ~changed /\ ~deferredBefore
                     THEN [durable EXCEPT !.pending = previous] ELSE durable
          /\ phase' = IF ~proceed THEN "done"
                      ELSE IF gated THEN "fetch consume" ELSE "acknowledge"
    /\ action' = "finish fetch"
    /\ UNCHANGED <<before, invocation, first, last, gated, forced, changed, threshold,
                   current, inputs, previous, deferredBefore, executed, stageForces,
                   failures, failedAt>>

Execute ==
    /\ phase = "stage" /\ current \in DerivedStages
    /\ durable' = [durable EXCEPT
        !.outputs[current] = IF current = 1 THEN durable.source ELSE durable.outputs[1],
        !.kmzVersion = IF current = 3 THEN @ + 1 ELSE @]
    /\ inputs' = IF current = 1 /\ gated THEN durable.source ELSE inputs
    /\ executed' = Append(executed, current)
    /\ stageForces' = Append(stageForces, EffectiveForce)
    /\ phase' = IF current = 3 THEN "commit publication" ELSE "acknowledge"
    /\ action' = "execute"
    /\ UNCHANGED <<before, invocation, first, last, gated, forced, changed, threshold,
                   current, previous, deferredBefore, failures, failedAt>>

Commit ==
    /\ phase = "commit publication"
    /\ durable' = IF inputs = Absent THEN durable ELSE
        [durable EXCEPT !.publication = inputs,
                        !.publicationVersion = durable.kmzVersion]
    /\ phase' = "invalidate publication" /\ action' = "commit"
    /\ UNCHANGED <<before, invocation, first, last, gated, forced, changed, threshold,
                   current, inputs, previous, deferredBefore, executed, stageForces,
                   failures, failedAt>>

Invalidate ==
    /\ phase = "invalidate publication"
    /\ durable' = IF gated /\ inputs = Absent THEN
        [durable EXCEPT !.publication = Absent, !.publicationVersion = Absent]
        ELSE durable
    /\ phase' = "acknowledge" /\ action' = "invalidate"
    /\ UNCHANGED <<before, invocation, first, last, gated, forced, changed, threshold,
                   current, inputs, previous, deferredBefore, executed, stageForces,
                   failures, failedAt>>

Acknowledge ==
    /\ phase = "acknowledge"
    /\ durable' = [durable EXCEPT !.pending = Complete(@, current)]
    /\ phase' = IF current = last THEN "done" ELSE "stage"
    /\ current' = IF current = last THEN current ELSE current + 1
    /\ action' = "acknowledge"
    /\ UNCHANGED <<before, invocation, first, last, gated, forced, changed, threshold,
                   inputs, previous, deferredBefore, executed, stageForces,
                   failures, failedAt>>

Crash ==
    /\ phase \in {"stage", "fetch consume", "fetch write", "fetch decide",
                   "acknowledge",
                   "commit publication", "invalidate publication"}
    /\ invocation <= ExploratoryInvocations /\ failures < MaximumFailures
    /\ failedAt' = phase /\ phase' = "done" /\ failures' = failures + 1
    /\ action' = "crash"
    /\ UNCHANGED <<durable, before, invocation, first, last, gated, forced, changed,
                   threshold, current, inputs, previous, deferredBefore, executed,
                   stageForces>>

NextInvocation ==
    /\ phase = "done" /\ invocation <= ExploratoryInvocations
    /\ phase' = "idle" /\ action' = "next"
    /\ UNCHANGED <<durable, before, invocation, first, last, gated, forced, changed,
                   threshold, current, inputs, previous, deferredBefore, executed,
                   stageForces, failures, failedAt>>

Progress == (\E start, finish \in 0..4, gate, force, change, qualifies \in BOOLEAN:
               /\ (change => start = 0 /\ durable.source = 0)
               /\ (qualifies => gate /\ start = 0)
               /\ Begin(start, finish, gate, force, change, qualifies))
            \/ StartFetch \/ ConsumeDeferred \/ Fetch \/ FinishFetch \/ Execute
            \/ Commit \/ Invalidate \/ Acknowledge \/ NextInvocation
Next == Progress \/ Crash
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Progress)

TypeOK == /\ durable.pending \in States /\ durable.source \in 0..1
          /\ durable.outputs \in [DerivedStages -> 0..1]
          /\ durable.deferred \in BOOLEAN /\ inputs \in {Absent, 0, 1}
          /\ invocation \in 0..(ExploratoryInvocations + 1)
          /\ failures \in 0..MaximumFailures
ObligationsSurvive == \A stage \in DerivedStages:
    durable.outputs[stage] # durable.source =>
        durable.deferred \/ stage \in Members(durable.pending.remaining)
PublicationHasPreparedInputs == ValidPublication =>
    durable.publication = durable.outputs[3] /\
    durable.publication <= durable.outputs[1]
SelectionRespected == \A index \in DOMAIN executed:
    first <= executed[index] /\ executed[index] <= last
ForceReachesRequiredStage == \A index \in DOMAIN executed:
    forced => stageForces[index]
InheritedForceReachesRequiredStage == \A index \in DOMAIN executed:
    before.pending.unconditional /\
    executed[index] \in Members(before.pending.remaining) => stageForces[index]
DeferredConsumptionIsProtected == action = "consume deferred" =>
    durable.pending.remaining = StageOrder
FinalRecovery == phase = "done" /\ invocation = ExploratoryInvocations + 1 =>
    durable.pending = EmptyState /\ ~durable.deferred /\
    \A stage \in DerivedStages: durable.outputs[stage] = durable.source
EventuallyRecovered == <>(phase = "done" /\ invocation = ExploratoryInvocations + 1)
=============================================================================
