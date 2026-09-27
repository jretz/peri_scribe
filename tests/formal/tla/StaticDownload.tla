---------------------------- MODULE StaticDownload ----------------------------
EXTENDS Naturals

CONSTANT TotalChunks
VARIABLES final, staged, phase, failed, observed
variables == <<final, staged, phase, failed, observed>>
Init ==
    /\ final \in {0, TotalChunks}
    /\ staged = 0
    /\ phase = "check"
    /\ failed = FALSE
    /\ observed = 0
Check ==
    /\ phase = "check"
    /\ phase' = IF final = TotalChunks THEN "done" ELSE "build"
    /\ observed' = final
    /\ UNCHANGED <<final, staged, failed>>
WriteChunk ==
    /\ phase = "build" /\ staged < TotalChunks
    /\ staged' = staged + 1
    /\ UNCHANGED <<final, phase, failed, observed>>
Finish ==
    /\ phase = "build" /\ staged = TotalChunks
    /\ phase' = "publish"
    /\ UNCHANGED <<final, staged, failed, observed>>
Publish ==
    /\ phase = "publish"
    /\ final' = staged
    /\ phase' = "done"
    /\ UNCHANGED <<staged, failed, observed>>
Fail ==
    /\ phase \in {"build", "publish"} /\ ~failed
    /\ failed' = TRUE
    /\ phase' = "check"
    /\ staged' = 0
    /\ UNCHANGED <<final, observed>>
Observe ==
    /\ observed' = final
    /\ UNCHANGED <<final, staged, phase, failed>>
Next == Check \/ WriteChunk \/ Finish \/ Publish \/ Fail \/ Observe
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Check) /\ WF_variables(WriteChunk)
                 /\ WF_variables(Finish) /\ WF_variables(Publish)
TypeOK ==
    /\ final \in 0..TotalChunks /\ staged \in 0..TotalChunks
    /\ observed \in 0..TotalChunks /\ failed \in BOOLEAN
    /\ phase \in {"check", "build", "publish", "done"}
ReusableMeansComplete == final \in {0, TotalChunks}
ReadersNeverSeePartial == observed \in {0, TotalChunks}
DoneHasCompleteData == phase = "done" => final = TotalChunks
EventuallyComplete == <> (phase = "done")
=============================================================================
