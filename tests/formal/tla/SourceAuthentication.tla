------------------------- MODULE SourceAuthentication -------------------------
EXTENDS Naturals, FiniteSets

CONSTANT Paths
VARIABLES scope, active, revisions, stamps, evidence, answer, reads, hashes
variables == <<scope, active, revisions, stamps, evidence, answer, reads, hashes>>

Init ==
    /\ scope = 0 /\ active = FALSE
    /\ revisions = [path \in Paths |-> 1]
    /\ stamps = [path \in Paths |-> 0]
    /\ evidence = [path \in Paths |-> <<0, 0, 0>>]
    /\ answer = <<0, 0>> /\ reads = 0 /\ hashes = 0

Begin ==
    /\ ~active /\ scope < 2
    /\ scope' = scope + 1 /\ active' = TRUE
    /\ UNCHANGED <<revisions, stamps, evidence, answer, reads, hashes>>

End ==
    /\ active /\ active' = FALSE
    /\ UNCHANGED <<scope, revisions, stamps, evidence, answer, reads, hashes>>

\* Reliable change metadata represents inode, ctime, size and mtime together. Even
\* restoring mtime after an in-place edit changes this token. Hashing one file is
\* atomic under the stable-operation assumption shared with ParsedCacheRead.
Edit(path) ==
    /\ stamps[path] < 2
    /\ revisions' = [revisions EXCEPT ![path] = 3 - @]
    /\ stamps' = [stamps EXCEPT ![path] = @ + 1]
    /\ UNCHANGED <<scope, active, evidence, answer, reads, hashes>>

Reusable(path) ==
    active /\ evidence[path][1] = scope /\ evidence[path][2] = stamps[path]

Authenticate(path) ==
    /\ reads < 4
    /\ answer' = <<IF Reusable(path) THEN evidence[path][3]
                   ELSE revisions[path], revisions[path]>>
    /\ evidence' = IF active THEN
         [evidence EXCEPT ![path] = <<scope, stamps[path], answer'[1]>>]
         ELSE evidence
    /\ reads' = reads + 1
    /\ hashes' = hashes + IF Reusable(path) THEN 0 ELSE 1
    /\ UNCHANGED <<scope, active, revisions, stamps>>

Next == Begin \/ End \/ (\E path \in Paths: Edit(path) \/ Authenticate(path))
Spec == Init /\ [][Next]_variables

AuthenticatedAnswer == answer[1] = answer[2]
LiveEvidenceMatchesBytes ==
    \A path \in Paths: Reusable(path) => evidence[path][3] = revisions[path]
NoCrossScopeReuse ==
    \A path \in Paths:
      evidence[path][1] # scope => ~Reusable(path)
NoExpiredReuse == ~active => \A path \in Paths: ~Reusable(path)
=============================================================================
