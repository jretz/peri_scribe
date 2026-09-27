---------------------------- MODULE SourceWriters -----------------------------
EXTENDS Naturals

Clients == 1..2
VARIABLES owner, phase, pending, forced, previous, previousForce, source, output,
          changed, failed
variables == <<owner, phase, pending, forced, previous, previousForce, source,
               output, changed, failed>>
Init ==
    /\ owner = 0 /\ phase = [client \in Clients |-> "start"]
    /\ pending \in BOOLEAN /\ forced \in BOOLEAN
    /\ previous = [client \in Clients |-> FALSE]
    /\ previousForce = [client \in Clients |-> FALSE]
    /\ source = 0 /\ output = 0
    /\ changed \in [Clients -> BOOLEAN]
    /\ failed = [client \in Clients |-> FALSE]
Acquire(client) ==
    /\ owner = 0 /\ phase[client] = "start"
    /\ owner' = client /\ phase' = [phase EXCEPT ![client] = "mark"]
    /\ UNCHANGED <<pending, forced, previous, previousForce, source, output,
                   changed, failed>>
Mark(client) ==
    /\ owner = client /\ phase[client] = "mark"
    /\ previous' = [previous EXCEPT ![client] = pending]
    /\ previousForce' = [previousForce EXCEPT ![client] = forced]
    /\ pending' = TRUE /\ phase' = [phase EXCEPT ![client] = "mutate"]
    /\ UNCHANGED <<owner, forced, source, output, changed, failed>>
Mutate(client) ==
    /\ owner = client /\ phase[client] = "mutate"
    /\ source' = IF changed[client] THEN client ELSE source
    /\ phase' = [phase EXCEPT ![client] = "return"]
    /\ UNCHANGED <<owner, pending, forced, previous, previousForce, output,
                   changed, failed>>
Return(client) ==
    /\ owner = client /\ phase[client] = "return"
    /\ pending' = IF changed[client] THEN pending ELSE previous[client]
    /\ forced' = IF changed[client] THEN forced ELSE previousForce[client]
    /\ phase' = [phase EXCEPT ![client] = IF client = 1 THEN "rebuild" ELSE "end"]
    /\ UNCHANGED <<owner, previous, previousForce, source, output, changed, failed>>
Rebuild ==
    /\ owner = 1 /\ phase[1] = "rebuild"
    /\ output' = source /\ pending' = FALSE /\ forced' = FALSE
    /\ phase' = [phase EXCEPT ![1] = "end"]
    /\ UNCHANGED <<owner, previous, previousForce, source, changed, failed>>
Release(client) ==
    /\ owner = client /\ phase[client] = "end"
    /\ owner' = 0 /\ phase' = [phase EXCEPT ![client] = "done"]
    /\ UNCHANGED <<pending, forced, previous, previousForce, source, output,
                   changed, failed>>
Crash(client) ==
    /\ owner = client /\ ~failed[client]
    /\ owner' = 0 /\ phase' = [phase EXCEPT ![client] = "start"]
    /\ failed' = [failed EXCEPT ![client] = TRUE]
    /\ UNCHANGED <<pending, forced, previous, previousForce, source, output, changed>>
Next == Rebuild \/ \E client \in Clients:
    Acquire(client) \/ Mark(client) \/ Mutate(client) \/ Return(client)
    \/ Release(client) \/ Crash(client)
Spec == Init /\ [][Next]_variables
TypeOK ==
    /\ owner \in 0..2 /\ source \in 0..2 /\ output \in 0..2
    /\ pending \in BOOLEAN /\ forced \in BOOLEAN
    /\ previous \in [Clients -> BOOLEAN] /\ previousForce \in [Clients -> BOOLEAN]
    /\ changed \in [Clients -> BOOLEAN] /\ failed \in [Clients -> BOOLEAN]
    /\ phase \in [Clients ->
          {"start", "mark", "mutate", "return", "rebuild", "end", "done"}]
OnlyOneWriter == \A client \in Clients:
    phase[client] \notin {"start", "done"} => owner = client
MutationIsMarked == \A client \in Clients: phase[client] = "mutate" => pending
NoLostRebuild == source # output => pending
=============================================================================
