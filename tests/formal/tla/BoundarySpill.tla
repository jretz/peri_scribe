--------------------------- MODULE BoundarySpill ---------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANT MaxTrace
Keys == 1..3
Sizes == [key \in Keys |-> IF key = 3 THEN 5 ELSE 2]
Budget == 4
VARIABLES scope, stored, corrupt, used, disabled, limit, result, trace
vars == <<scope, stored, corrupt, used, disabled, limit, result, trace>>

Init == /\ scope = "new" /\ stored = {} /\ corrupt = {}
        /\ used = 0 /\ disabled = FALSE /\ limit \in {1, 2}
        /\ result = 0 /\ trace = <<>>

Room(key) == ~disabled /\ key \notin stored
             /\ Cardinality(stored) < limit /\ used + Sizes[key] <= Budget

Open == /\ scope = "new" /\ scope' = "active"
        /\ trace' = Append(trace, 1)
        /\ UNCHANGED <<stored, corrupt, used, disabled, limit, result>>

Put(key, fails) ==
    /\ scope = "active"
    /\ IF Room(key)
          THEN /\ used' = used + Sizes[key]
               /\ stored' = IF fails THEN stored ELSE stored \cup {key}
               /\ disabled' = fails
          ELSE UNCHANGED <<used, stored, disabled>>
    /\ trace' = Append(trace, (IF fails THEN 20 ELSE 10) + key)
    /\ UNCHANGED <<scope, corrupt, limit, result>>

Read(key) == /\ scope = "active"
             /\ result' = IF key \in stored \ corrupt THEN key ELSE 0
             /\ trace' = Append(trace, 30 + key)
             /\ UNCHANGED <<scope, stored, corrupt, used, disabled, limit>>

Damage(key) == /\ scope = "active" /\ key \in stored
               /\ corrupt' = corrupt \cup {key}
               /\ trace' = Append(trace, 40 + key)
               /\ UNCHANGED <<scope, stored, used, disabled, limit, result>>

Close == /\ scope = "active" /\ scope' = "closed"
         /\ stored' = {} /\ corrupt' = {} /\ used' = 0 /\ result' = 0
         /\ trace' = Append(trace, 2)
         /\ UNCHANGED <<disabled, limit>>

Next == /\ Len(trace) < MaxTrace
        /\ (Open \/ Close \/ \E key \in Keys:
              Put(key, FALSE) \/ Put(key, TRUE) \/ Read(key) \/ Damage(key))
Spec == Init /\ [][Next]_vars

TypeOK == /\ scope \in {"new", "active", "closed"}
          /\ stored \subseteq Keys /\ corrupt \subseteq stored
          /\ used \in 0..Budget /\ disabled \in BOOLEAN
          /\ limit \in {1, 2} /\ result \in 0..3
Bounded == Cardinality(stored) <= limit /\ used <= Budget
ClosedEmpty == scope = "closed" => stored = {} /\ used = 0
FreshOnly == stored \subseteq {key \in Keys: \E i \in 1..Len(trace): trace[i] = 10 + key}
AuthenticRead == Len(trace) > 0 /\ trace[Len(trace)] \in 31..33 =>
    result = IF (trace[Len(trace)] - 30) \in stored \ corrupt
             THEN trace[Len(trace)] - 30 ELSE 0
=============================================================================
