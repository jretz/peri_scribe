------------------------- MODULE ParsedCacheRebuild --------------------------
EXTENDS Naturals

VARIABLES source, phase, tables, receipt, rows, memberships, restarted, answer
variables == <<source, phase, tables, receipt, rows, memberships, restarted, answer>>

Read(t, c, r, m) ==
    IF t = {"snapshots", "rows", "memberships"} /\ c = source
    THEN <<r, m>> ELSE <<>>

Init ==
    /\ source \in 1..2 /\ phase = 0
    /\ tables = {"snapshots", "rows", "memberships"}
    /\ receipt = 1 /\ rows = 1 /\ memberships = 1 /\ restarted = FALSE
    /\ answer = Read(tables, receipt, rows, memberships)

Reset ==
    /\ phase < 8 /\ phase' = phase + 1
    /\ tables' = CASE phase = 0 -> tables \ {"rows"}
                    [] phase = 1 -> tables \ {"memberships"}
                    [] phase = 2 -> tables \ {"snapshots"}
                    [] phase = 3 -> tables \cup {"snapshots"}
                    [] phase = 4 -> tables \cup {"rows"}
                    [] phase = 6 -> tables \cup {"memberships"}
                    [] OTHER -> tables
    /\ receipt' = IF phase \in {2, 3} THEN 0 ELSE receipt
    /\ rows' = IF phase \in {0, 4} THEN 0 ELSE rows
    /\ memberships' = IF phase \in {1, 6} THEN 0 ELSE memberships
    /\ answer' = Read(tables', receipt', rows', memberships')
    /\ UNCHANGED <<source, restarted>>
CrashAndRestart ==
    /\ phase \in 0..8 /\ ~restarted
    /\ phase' = 0 /\ restarted' = TRUE
    /\ UNCHANGED <<source, tables, receipt, rows, memberships, answer>>
Synchronize ==
    /\ phase = 8 /\ phase' = 9
    /\ receipt' = source /\ rows' = source /\ memberships' = source
    /\ answer' = <<source, source>>
    /\ UNCHANGED <<source, tables, restarted>>
Next == Reset \/ CrashAndRestart \/ Synchronize
Spec == Init /\ [][Next]_variables
NoPartialRebuildRead == answer # <<>> => answer = <<source, source>>
SuccessfulRebuildMatchesSource == phase = 9 => answer = <<source, source>>
=============================================================================
