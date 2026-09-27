------------------------------ MODULE FeedCache ------------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANT MaxSnapshots
VARIABLES updates, count, tag, cache, readable, phase, candidate
variables == <<updates, count, tag, cache, readable, phase, candidate>>
Objects == 1..2
Values == 1..2
Empty == [object \in Objects |-> 0]
Apply(state, update) == [state EXCEPT ![update.object] = update.value]
RECURSIVE Replay(_)
Replay(n) == IF n = 0 THEN Empty ELSE Apply(Replay(n - 1), updates[n])
Init ==
    /\ updates \in [1..MaxSnapshots -> [object : Objects, value : Values]]
    /\ count \in 1..MaxSnapshots
    /\ tag \in 0..MaxSnapshots
    /\ cache = Replay(tag)
    /\ readable \in BOOLEAN
    /\ phase = "idle"
    /\ candidate = Empty
Prepare ==
    /\ phase = "idle"
    /\ candidate' = Apply(
          IF readable /\ tag \in {count, count - 1} THEN cache ELSE Replay(count),
          updates[count])
    /\ phase' = "writing"
    /\ UNCHANGED <<updates, count, tag, cache, readable>>
Publish ==
    /\ phase = "writing"
    /\ cache' = candidate
    /\ tag' = count
    /\ readable' = TRUE
    /\ phase' = "done"
    /\ UNCHANGED <<updates, count, candidate>>
\* A failed staging write does not expose its partial contents as the current cache.
FailWrite ==
    /\ phase = "writing"
    /\ phase' = "idle"
    /\ UNCHANGED <<updates, count, tag, cache, readable, candidate>>
Next == Prepare \/ Publish \/ FailWrite
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Prepare) /\ SF_variables(Publish)
TypeOK ==
    /\ count \in 1..MaxSnapshots /\ tag \in 0..MaxSnapshots
    /\ cache \in [Objects -> 0..2] /\ candidate \in [Objects -> 0..2]
    /\ readable \in BOOLEAN /\ phase \in {"idle", "writing", "done"}
FreshCacheEqualsReplay == readable /\ tag = count => cache = Replay(count)
PublishedCacheEqualsReplay == phase = "done" => cache = Replay(count)
SafeCandidate == phase = "writing" => candidate = Replay(count)
EventuallyPublished == <> (phase = "done")
=============================================================================
