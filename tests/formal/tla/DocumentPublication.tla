-------------------------- MODULE DocumentPublication --------------------------
EXTENDS Naturals

CONSTANT TotalChunks
VARIABLES prior, published, staged, orphan, phase, failed, reader
variables == <<prior, published, staged, orphan, phase, failed, reader>>
Init ==
    /\ prior \in {0, 1}
    /\ published = prior /\ staged = 0 /\ orphan = 0
    /\ phase = "write" /\ failed = FALSE /\ reader = prior
Write ==
    /\ phase = "write" /\ staged < TotalChunks
    /\ staged' = staged + 1
    /\ UNCHANGED <<prior, published, orphan, phase, failed, reader>>
Close ==
    /\ phase = "write" /\ staged = TotalChunks /\ phase' = "replace"
    /\ UNCHANGED <<prior, published, staged, orphan, failed, reader>>
Replace ==
    /\ phase = "replace" /\ published' = 2 /\ phase' = "done"
    /\ UNCHANGED <<prior, staged, orphan, failed, reader>>
\* The canonical name is the only public entry point; abandoned staging is private.
Crash ==
    /\ phase # "done" /\ ~failed
    /\ orphan' = staged /\ staged' = 0 /\ phase' = "write" /\ failed' = TRUE
    /\ UNCHANGED <<prior, published, reader>>
Read ==
    /\ reader' = published
    /\ UNCHANGED <<prior, published, staged, orphan, phase, failed>>
Next == Write \/ Close \/ Replace \/ Crash \/ Read
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Write) /\ WF_variables(Close)
                 /\ WF_variables(Replace)
TypeOK ==
    /\ prior \in {0, 1} /\ published \in 0..2
    /\ staged \in 0..TotalChunks /\ orphan \in 0..TotalChunks
    /\ phase \in {"write", "replace", "done"} /\ failed \in BOOLEAN
    /\ reader \in 0..2
PublishedIsComplete == published \in {prior, 2}
ReaderIsComplete == reader \in {prior, 2}
PriorSurvivesUntilReplace == phase # "done" => published = prior
SuccessfulWriteIsVisible == phase = "done" => published = 2
EventuallyPublished == <> (phase = "done")
=============================================================================
