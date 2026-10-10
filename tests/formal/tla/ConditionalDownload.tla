-------------------------- MODULE ConditionalDownload -------------------------
EXTENDS Naturals

VARIABLES previous, validators, final, phase, request, staged, validated, outcome
variables == <<previous, validators, final, phase, request, staged,
               validated, outcome>>

Init ==
    /\ previous \in {0, 1}
    /\ validators \in {"none", "modified", "etag", "both"}
    /\ final = previous
    /\ phase = "start"
    /\ request = "unset"
    /\ staged = 0
    /\ validated = FALSE
    /\ outcome = "pending"

Request ==
    /\ phase = "start"
    /\ request' = IF previous = 0 THEN "none"
                   ELSE IF validators \in {"etag", "both"} THEN "etag"
                   ELSE validators
    /\ phase' = "response"
    /\ UNCHANGED <<previous, validators, final, staged, validated, outcome>>

NotModified ==
    /\ phase = "response"
    /\ phase' = "done"
    /\ outcome' = IF previous = 1 THEN "cached" ELSE "fatal"
    /\ UNCHANGED <<previous, validators, final, request, staged, validated>>

Download ==
    /\ phase = "response"
    /\ staged' = 1
    /\ phase' = "convert"
    /\ UNCHANGED <<previous, validators, final, request, validated, outcome>>

Convert ==
    /\ phase = "convert"
    /\ staged' = 2
    /\ phase' = "validate"
    /\ UNCHANGED <<previous, validators, final, request, validated, outcome>>

Validate ==
    /\ phase = "validate"
    /\ validated' = TRUE
    /\ phase' = "publish"
    /\ UNCHANGED <<previous, validators, final, request, staged, outcome>>

Publish ==
    /\ phase = "publish"
    /\ final' = 2
    /\ phase' = "done"
    /\ outcome' = "fresh"
    /\ UNCHANGED <<previous, validators, request, staged, validated>>

Fail ==
    /\ phase \in {"response", "convert", "validate", "publish"}
    /\ phase' = "done"
    /\ outcome' = IF previous = 1 THEN "cached" ELSE "fatal"
    /\ UNCHANGED <<previous, validators, final, request, staged, validated>>

Crash ==
    /\ phase \in {"response", "convert", "validate", "publish", "done"}
    /\ phase' = "crashed"
    /\ outcome' = "interrupted"
    /\ UNCHANGED <<previous, validators, final, request, staged, validated>>

Next == Request \/ NotModified \/ Download \/ Convert \/ Validate \/ Publish
        \/ Fail \/ Crash
Spec == Init /\ [][Next]_variables

TypeOK ==
    /\ previous \in {0, 1}
    /\ validators \in {"none", "modified", "etag", "both"}
    /\ final \in 0..2
    /\ phase \in {"start", "response", "convert", "validate", "publish",
                  "done", "crashed"}
    /\ request \in {"unset", "none", "modified", "etag"}
    /\ staged \in 0..2
    /\ validated \in BOOLEAN
    /\ outcome \in {"pending", "cached", "fatal", "fresh", "interrupted"}

OnlyValidatedReplacement == final = 2 => staged = 2 /\ validated
PreviousSurvivesUntilReplacement == final \in {previous, 2}
FailurePreservesPrevious == outcome \in {"cached", "fatal"} => final = previous
SuccessfulReturnHasUsableData == outcome \in {"cached", "fresh"} => final > 0
MissingDataMakesFailureFatal == outcome = "fatal" <=>
                               (phase = "done" /\ final = 0)
ConditionalNeedsUsableData == request \in {"modified", "etag"} => previous = 1
PreferredValidator == request # "unset" =>
    request = IF previous = 0 THEN "none"
              ELSE IF validators \in {"etag", "both"} THEN "etag"
              ELSE validators
EveryCompletionRequested == phase \in {"done", "crashed"} => request # "unset"
=============================================================================
