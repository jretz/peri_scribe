-------------------------- MODULE SnapshotPublication --------------------------
EXTENDS Naturals, Sequences

CONSTANT TotalChunks
VARIABLES prior, matching, full, files, staged, orphan, phase, failed, cache
variables == <<prior, matching, full, files, staged, orphan, phase, failed, cache>>
Init ==
    /\ prior \in {0, 1}
    /\ matching \in BOOLEAN /\ (matching => prior = 1)
    /\ full \in BOOLEAN
    /\ files = IF prior = 1 THEN <<TotalChunks>> ELSE <<>>
    /\ staged = 0 /\ orphan = 0
    /\ phase = "check" /\ failed = FALSE /\ cache = FALSE
Check ==
    /\ phase = "check"
    /\ phase' = IF matching /\ ~full THEN "done" ELSE "write"
    /\ UNCHANGED <<prior, matching, full, files, staged, orphan, failed, cache>>
Write ==
    /\ phase = "write" /\ staged < TotalChunks
    /\ staged' = staged + 1
    /\ UNCHANGED <<prior, matching, full, files, orphan, phase, failed, cache>>
Finish ==
    /\ phase = "write" /\ staged = TotalChunks
    /\ phase' = "publish"
    /\ UNCHANGED <<prior, matching, full, files, staged, orphan, failed, cache>>
Publish ==
    /\ phase = "publish"
    /\ files' = Append(files, staged)
    /\ phase' = "cache"
    /\ UNCHANGED <<prior, matching, full, staged, orphan, failed, cache>>
Cache ==
    /\ phase = "cache"
    /\ cache' \in BOOLEAN
    /\ phase' = "done"
    /\ UNCHANGED <<prior, matching, full, files, staged, orphan, failed>>
\* Abrupt termination can leave staging bytes but cannot give them a snapshot name.
Crash ==
    /\ phase \in {"write", "publish"} /\ ~failed
    /\ orphan' = staged /\ staged' = 0
    /\ failed' = TRUE /\ phase' = "check"
    /\ UNCHANGED <<prior, matching, full, files, cache>>
Next == Check \/ Write \/ Finish \/ Publish \/ Cache \/ Crash
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Check) /\ WF_variables(Write)
                 /\ WF_variables(Finish) /\ WF_variables(Publish)
                 /\ WF_variables(Cache)
TypeOK ==
    /\ prior \in {0, 1} /\ matching \in BOOLEAN /\ full \in BOOLEAN
    /\ files \in Seq(0..TotalChunks) /\ Len(files) <= 2
    /\ staged \in 0..TotalChunks /\ orphan \in 0..TotalChunks
    /\ phase \in {"check", "write", "publish", "cache", "done"}
    /\ failed \in BOOLEAN /\ cache \in BOOLEAN
DiscoverableMeansComplete == \A serial \in DOMAIN files: files[serial] = TotalChunks
OriginalPreserved == prior = 1 => files[1] = TotalChunks
CacheFollowsSnapshot == cache => Len(files) = prior + 1
DoneHasSnapshot == phase = "done" => Len(files) > 0
FullWriteAppends == phase = "done" /\ full => Len(files) = prior + 1
EventuallyComplete == <> (phase = "done")
=============================================================================
