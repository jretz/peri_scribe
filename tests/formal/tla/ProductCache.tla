----------------------------- MODULE ProductCache -----------------------------
EXTENDS CacheDefinitions

VARIABLES durable, pending, phase, interrupted, disabled, artifact, trace
variables == <<durable, pending, phase, interrupted, disabled, artifact, trace>>

Initial == [generation |-> 1, payloads |-> {1, 2}]
Init == /\ durable = Initial /\ pending = Initial /\ phase = 0
        /\ interrupted = FALSE /\ disabled = FALSE /\ artifact = 1 /\ trace = <<>>

\* Each update is a separate SQLite statement in one owning scope/transaction.
Begin == /\ phase = 0 /\ pending' = durable /\ phase' = 1 /\ artifact' = 2
         /\ UNCHANGED <<durable, interrupted, disabled>>
Payload(key, expectedPhase) ==
    /\ phase = expectedPhase /\ ~disabled
    /\ pending' = [pending EXCEPT !.payloads = @ \cup {key}]
    /\ phase' = phase + 1
    /\ UNCHANGED <<durable, interrupted, disabled, artifact>>
Manifest ==
    /\ phase = 3 /\ ~disabled
    /\ pending' = [pending EXCEPT !.generation = 2] /\ phase' = 4
    /\ UNCHANGED <<durable, interrupted, disabled, artifact>>
Prune ==
    /\ phase = 4 /\ ~disabled
    /\ pending' = [pending EXCEPT !.payloads = @ \cap Required(2)] /\ phase' = 5
    /\ UNCHANGED <<durable, interrupted, disabled, artifact>>
StatementFailure ==
    /\ phase \in 1..4 /\ ~disabled /\ disabled' = TRUE /\ phase' = 5
    /\ UNCHANGED <<durable, pending, interrupted, artifact>>
Commit ==
    /\ phase = 5 /\ durable' = pending /\ phase' = 6
    /\ UNCHANGED <<pending, interrupted, disabled, artifact>>
\* Exceptions and failed commits close an uncommitted connection. One retry is enough
\* to expose every interruption boundary without assuming successful progress.
Abort ==
    /\ phase \in 1..5 /\ ~interrupted
    /\ interrupted' = TRUE /\ pending' = durable /\ disabled' = FALSE /\ phase' = 0
    /\ UNCHANGED <<durable, artifact>>
Next == \/ Begin /\ trace' = Append(trace, 1)
        \/ Payload(3, 1) /\ trace' = Append(trace, 2)
        \/ Payload(2, 2) /\ trace' = Append(trace, 3)
        \/ Manifest /\ trace' = Append(trace, 4)
        \/ Prune /\ trace' = Append(trace, 5)
        \/ StatementFailure /\ trace' = Append(trace, 6)
        \/ Commit /\ trace' = Append(trace, 7)
        \/ Abort /\ trace' = Append(trace, 8)
Spec == Init /\ [][Next]_variables

DurableGenerationIsComplete == Required(durable.generation) \subseteq durable.payloads
PendingManifestIsComplete == Required(pending.generation) \subseteq pending.payloads
NoPartialGenerationReuse ==
    \A requested \in SUBSET Keys:
      LET answer == Read(durable.generation, durable.payloads, 0, requested,
                         artifact, TRUE, FALSE, TRUE)
      IN answer # <<0>> => answer = Selected(artifact, requested)
=============================================================================
