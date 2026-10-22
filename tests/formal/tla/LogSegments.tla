------------------------------ MODULE LogSegments ------------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANT MaximumFailures
VARIABLES active, sealed, archives, receipts, removed, expected, phase, slot,
          late, failures
variables == <<active, sealed, archives, receipts, removed, expected, phase, slot,
               late, failures>>

Init ==
    /\ active = <<1, 1>> /\ sealed = <<>>
    /\ archives = {} /\ receipts = {} /\ removed = {}
    /\ expected = <<2, 1, 1>> /\ phase = "idle" /\ slot = 0
    /\ late = FALSE /\ failures = MaximumFailures

\* The legacy monthly archive is an older prefix. Sealing is one atomic rename.
Seal ==
    /\ phase = "idle" /\ active # <<>> /\ Len(sealed) < 2
    /\ sealed' = Append(sealed, active) /\ active' = <<>>
    /\ slot' = Len(sealed) + 1 /\ phase' = "receipt"
    /\ UNCHANGED <<archives, receipts, removed, expected, late, failures>>
WriteReceipt ==
    /\ phase = "receipt" /\ receipts' = receipts \cup {slot}
    /\ phase' = "publish"
    /\ UNCHANGED <<active, sealed, archives, removed, expected, slot, late, failures>>
PublishArchive ==
    /\ phase = "publish" /\ archives' = archives \cup {slot}
    /\ phase' = "unlink"
    /\ UNCHANGED <<active, sealed, receipts, removed, expected, slot, late, failures>>
RemovePlain ==
    /\ phase = "unlink" /\ removed' = removed \cup {slot}
    /\ phase' = "forget"
    /\ UNCHANGED <<active, sealed, archives, receipts, expected, slot, late, failures>>
ForgetReceipt ==
    /\ phase = "forget" /\ receipts' = receipts \ {slot} /\ phase' = "idle"
    /\ UNCHANGED <<active, sealed, archives, removed, expected, slot, late, failures>>
AppendLate ==
    /\ phase = "idle" /\ ~late /\ Len(sealed) = 1
    /\ late' = TRUE /\ active' = <<1>> /\ expected' = expected \o <<1>>
    /\ UNCHANGED <<sealed, archives, receipts, removed, phase, slot, failures>>
Recover ==
    /\ phase = "recover"
    /\ phase' = IF slot \in archives
                THEN IF slot \in removed THEN "forget" ELSE "unlink"
                ELSE "receipt"
    /\ UNCHANGED <<active, sealed, archives, receipts, removed, expected, slot,
                   late, failures>>
Crash ==
    /\ phase \notin {"idle", "recover"} /\ failures > 0
    /\ phase' = "recover" /\ failures' = failures - 1
    /\ UNCHANGED <<active, sealed, archives, receipts, removed, expected, slot, late>>
Next == Seal \/ WriteReceipt \/ PublishArchive \/ RemovePlain \/ ForgetReceipt
        \/ AppendLate \/ Recover \/ Crash
Spec == Init /\ [][Next]_variables

RECURSIVE Flatten(_)
Flatten(items) == IF Len(items) = 0 THEN <<>> ELSE Head(items) \o Flatten(Tail(items))
SegmentContents(index) ==
    IF index \in archives /\ index \in receipts THEN sealed[index]
    ELSE (IF index \in archives THEN sealed[index] ELSE <<>>) \o
         (IF index \notin removed THEN sealed[index] ELSE <<>>)
LogicalContents == <<2>> \o
    Flatten([index \in 1..Len(sealed) |-> SegmentContents(index)]) \o active
TypeOK ==
    /\ active \in Seq({1}) /\ sealed \in Seq(Seq({1})) /\ Len(sealed) <= 2
    /\ archives \subseteq 1..Len(sealed)
    /\ receipts \subseteq 1..Len(sealed) /\ removed \subseteq 1..Len(sealed)
    /\ expected \in Seq({1, 2}) /\ Len(expected) <= 4
    /\ phase \in {"idle", "receipt", "publish", "unlink", "forget", "recover"}
    /\ slot \in 0..2 /\ late \in BOOLEAN /\ failures \in 0..MaximumFailures
NoLossOrDuplication == LogicalContents = expected
RetirementRequiresArchive == removed \subseteq archives
PublishedUnretiredHasReceipt == archives \ removed \subseteq receipts
EarlierSegmentsComplete ==
    \A index \in 1..Len(sealed): index < slot => index \in removed /\ index \notin receipts
=============================================================================
