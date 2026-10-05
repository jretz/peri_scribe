---------------------------- MODULE BrowserRefresh ----------------------------
EXTENDS Naturals

Kinds == {"none", "changed", "unchanged"}
Responses == {"ok", "network error", "ignored condition", "get error", "invalid",
              "not modified"}
VARIABLES kind, response, phase, displayed, validator, beforeDisplayed,
          beforeValidator, round, skipped, requests, active, conditional, bodyReads,
          failures
variables == <<kind, response, phase, displayed, validator, beforeDisplayed,
               beforeValidator, round, skipped, requests, active, conditional,
               bodyReads, failures>>

Server == IF kind = "unchanged" THEN 0 ELSE 1
Init ==
    /\ kind \in Kinds /\ response \in Responses
    /\ phase = "idle" /\ displayed = 0 /\ validator = 0
    /\ beforeDisplayed = 0 /\ beforeValidator = 0
    /\ round = 1 /\ skipped = 0 /\ requests = 0 /\ active = 0
    /\ conditional = FALSE /\ bodyReads = 0 /\ failures = 0

Start ==
    /\ phase = "idle" /\ phase' = "get" /\ active' = active + 1
    /\ requests' = requests + 1
    /\ conditional' = (kind # "none")
    /\ beforeDisplayed' = displayed /\ beforeValidator' = validator
    /\ UNCHANGED <<kind, response, displayed, validator, round, skipped, bodyReads,
                   failures>>

Same == beforeValidator = Server
NotModified == response = "not modified" \/
               (response = "ok" /\ conditional /\ Same)
Failure == response \in {"network error", "get error", "invalid"} \/
           (NotModified /\ ~conditional)

Download ==
    /\ phase = "get" /\ phase' = "finish"
    /\ displayed' = IF Failure \/ NotModified THEN displayed ELSE Server
    /\ validator' = IF Failure \/ NotModified THEN validator ELSE Server
    /\ bodyReads' = IF response \in {"network error", "get error"} \/ NotModified
                    THEN bodyReads ELSE bodyReads + 1
    /\ failures' = IF Failure THEN failures + 1 ELSE failures
    /\ UNCHANGED <<kind, response, beforeDisplayed, beforeValidator, round, skipped,
                   requests, active, conditional>>

Overlap ==
    /\ phase = "get" /\ skipped = 0 /\ skipped' = 1
    /\ UNCHANGED <<kind, response, phase, displayed, validator, beforeDisplayed,
                   beforeValidator, round, requests, active, conditional, bodyReads,
                   failures>>

Finish ==
    /\ phase = "finish" /\ active' = active - 1 /\ phase' = "done"
    /\ UNCHANGED <<kind, response, displayed, validator, beforeDisplayed,
                   beforeValidator, round, skipped, requests, conditional, bodyReads,
                   failures>>

Retry ==
    /\ phase = "done" /\ round = 1 /\ round' = 2 /\ phase' = "idle"
    /\ response' = "ok" /\ requests' = 0 /\ skipped' = 0
    /\ bodyReads' = 0 /\ failures' = 0
    /\ UNCHANGED <<kind, displayed, validator, beforeDisplayed, beforeValidator,
                   active, conditional>>

Next == Start \/ Download \/ Overlap \/ Finish \/ Retry
Spec == Init /\ [][Next]_variables
FairSpec == Spec /\ WF_variables(Start)
                 /\ WF_variables(Download) /\ WF_variables(Finish)
                 /\ WF_variables(Retry)
TypeOK == /\ kind \in Kinds /\ response \in Responses
          /\ displayed \in {0, 1} /\ validator \in {0, 1}
          /\ round \in {1, 2} /\ active \in {0, 1}
          /\ requests \in 0..1 /\ skipped \in {0, 1}
          /\ conditional \in BOOLEAN
          /\ bodyReads \in 0..1 /\ failures \in 0..1
SingleRefresh == active = IF phase \in {"get", "finish"} THEN 1 ELSE 0
SingleRequest == phase = "done" => requests = 1
ConditionalRequiresValidator ==
    phase \in {"get", "finish", "done"} =>
        conditional = (kind # "none")
ValidatorsDescribeDisplay == validator = displayed
FailurePreservesSnapshot ==
    phase = "done" /\ Failure =>
        displayed = beforeDisplayed /\ validator = beforeValidator
NotModifiedPreservesSnapshot ==
    phase = "done" /\ NotModified =>
        displayed = beforeDisplayed /\ validator = beforeValidator
NotModifiedReadsNoBody == phase = "done" /\ NotModified => bodyReads = 0
HealthyRefreshIsCurrent == phase = "done" /\ response = "ok" => displayed = Server
EventuallyCurrent == <>(round = 2 /\ phase = "done" /\ displayed = Server)
=============================================================================
