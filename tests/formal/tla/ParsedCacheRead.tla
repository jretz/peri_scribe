--------------------------- MODULE ParsedCacheRead ---------------------------
EXTENDS Naturals

CONSTANT PinnedRead
VARIABLES before, after, checksum, commitAt, failureAt, phase, durable,
          pinned, authenticated, rows, memberships, answer
variables == <<before, after, checksum, commitAt, failureAt, phase, durable,
               pinned, authenticated, rows, memberships, answer>>

Init ==
    /\ before \in 0..2 /\ after \in 0..2 /\ checksum \in 1..2
    /\ commitAt \in 0..3 /\ failureAt \in 0..3
    /\ phase = 0 /\ durable = before /\ pinned = 0
    /\ authenticated = FALSE /\ rows = 0 /\ memberships = 0 /\ answer = <<>>

Current == IF commitAt = phase THEN after ELSE durable
View == IF PinnedRead /\ phase > 0 THEN pinned ELSE Current
Read ==
    /\ phase < 3
    /\ durable' = Current
    /\ pinned' = IF phase = 0 THEN Current ELSE pinned
    /\ authenticated' = IF phase = 0 THEN Current = checksum ELSE authenticated
    /\ IF failureAt = phase + 1
          \/ (phase = 0 /\ Current # checksum)
       THEN /\ phase' = 3 /\ answer' = <<>>
            /\ UNCHANGED <<rows, memberships>>
       ELSE /\ phase' = phase + 1
            /\ rows' = IF phase = 1 THEN View ELSE rows
            /\ memberships' = IF phase = 2 THEN View ELSE memberships
            /\ answer' = IF phase = 2 THEN <<rows, View>> ELSE <<>>
    /\ UNCHANGED <<before, after, checksum, commitAt, failureAt>>
Next == Read
Spec == Init /\ [][Next]_variables
AuthenticatedAnswer == answer # <<>> => answer = <<checksum, checksum>>
NoFailedRead == failureAt > 0 => answer = <<>>
=============================================================================
