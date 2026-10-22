----------------------- MODULE ParsedCacheCompaction -----------------------
EXTENDS Naturals, Sequences, TLC

CONSTANT TableCount
Tables == 1..TableCount
Payloads == {<<1>>, <<2>>, <<1, 2>>, <<2, 1>>, <<1, 1>>, <<2, 1, 2>>}
VARIABLES original, durable, staged, copied, phase, observed
variables == <<original, durable, staged, copied, phase, observed>>

Init ==
    /\ original \in Payloads
    /\ durable = [table \in Tables |-> original]
    /\ staged = [table \in Tables |-> <<>>]
    /\ copied = 0
    /\ phase = "copy"
    /\ observed = durable

Copy ==
    /\ phase = "copy" /\ copied < TableCount
    /\ staged' \in {
           [staged EXCEPT ![copied + 1] = original],
           [staged EXCEPT ![copied + 1] = Append(original, 9)]}
    /\ copied' = copied + 1
    /\ UNCHANGED <<original, durable, phase, observed>>

Validate ==
    /\ phase = "copy" /\ copied = TableCount
    /\ phase' = IF staged = durable THEN "validated" ELSE "failed"
    /\ UNCHANGED <<original, durable, staged, copied, observed>>

Close ==
    /\ phase = "validated" /\ phase' = "closed"
    /\ UNCHANGED <<original, durable, staged, copied, observed>>

Publish ==
    /\ phase = "closed"
    /\ durable' = staged /\ phase' = "published"
    /\ UNCHANGED <<original, staged, copied, observed>>

Fail ==
    /\ phase \in {"copy", "validated", "closed"}
    /\ phase' = "failed"
    /\ UNCHANGED <<original, durable, staged, copied, observed>>

Observe ==
    /\ observed' = durable
    /\ UNCHANGED <<original, durable, staged, copied, phase>>

Next == Copy \/ Validate \/ Close \/ Publish \/ Fail \/ Observe
Spec == Init /\ [][Next]_variables
TypeOK ==
    /\ original \in Payloads /\ copied \in 0..TableCount
    /\ phase \in {"copy", "validated", "closed", "published", "failed"}
DurableContentsPreserved == durable = [table \in Tables |-> original]
ReadersKeepCompleteData == observed = [table \in Tables |-> original]
OnlyValidatedDataPublishes ==
    phase \in {"validated", "closed", "published"} => staged = durable
=============================================================================
