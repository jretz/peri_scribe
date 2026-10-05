---------------------------- MODULE BrowserRefresh ----------------------------
EXTENDS Naturals

Kinds == {"none", "weak", "strong", "unchanged"}
Responses == {"ok", "network error", "ignored condition", "get error", "invalid",
              "not modified"}
VARIABLES kind, initialAge, response, phase, displayed, validator, age,
          beforeDisplayed, beforeValidator, beforeAge, round,
          firstDisplayed, firstAge, skipped, requests, active, conditional,
          bodyReads, failures
variables == <<kind, initialAge, response, phase, displayed, validator, age,
               beforeDisplayed, beforeValidator, beforeAge, round,
               firstDisplayed, firstAge, skipped, requests, active, conditional,
               bodyReads, failures>>

Server == IF kind = "unchanged" THEN 0 ELSE 1
Init ==
    /\ kind \in Kinds /\ initialAge \in {0, 2} /\ response \in Responses
    /\ phase = "idle" /\ displayed = 0 /\ validator = 0 /\ age = initialAge
    /\ beforeDisplayed = 0 /\ beforeValidator = 0 /\ beforeAge = initialAge
    /\ round = 1 /\ firstDisplayed = 0
    /\ firstAge = initialAge /\ skipped = 0 /\ requests = 0 /\ active = 0
    /\ conditional = FALSE /\ bodyReads = 0 /\ failures = 0

Start ==
    /\ phase = "idle" /\ phase' = "get" /\ active' = active + 1
    /\ requests' = requests + 1
    /\ conditional' = (kind \in {"strong", "unchanged"} \/
                       (kind = "weak" /\ age < 2))
    /\ beforeDisplayed' = displayed /\ beforeValidator' = validator
    /\ beforeAge' = age
    /\ UNCHANGED <<kind, initialAge, response, displayed, validator, age,
                   round, firstDisplayed, firstAge, skipped, bodyReads, failures>>

Same == kind \in {"unchanged", "weak"}
        \/ (kind = "strong" /\ beforeValidator = Server)
NotModified == response = "not modified" \/
               (response = "ok" /\ conditional /\ Same)
Failure == response \in {"network error", "get error", "invalid"} \/
           (NotModified /\ ~conditional)

Download ==
    /\ phase = "get" /\ phase' = "finish"
    /\ displayed' = IF Failure \/ NotModified THEN displayed ELSE Server
    /\ validator' = IF Failure \/ NotModified THEN validator ELSE Server
    /\ age' = IF Failure \/ NotModified THEN age ELSE 0
    /\ bodyReads' = IF response \in {"network error", "get error"} \/ NotModified
                    THEN bodyReads ELSE bodyReads + 1
    /\ failures' = IF Failure THEN failures + 1 ELSE failures
    /\ UNCHANGED <<kind, initialAge, response, beforeDisplayed, beforeValidator,
                   beforeAge, round, firstDisplayed, firstAge, skipped,
                   requests, active, conditional>>

Overlap ==
    /\ phase = "get" /\ skipped = 0 /\ skipped' = 1
    /\ UNCHANGED <<kind, initialAge, response, phase, displayed, validator, age,
                   beforeDisplayed, beforeValidator, beforeAge, round,
                   firstDisplayed, firstAge, requests, active, conditional,
                   bodyReads, failures>>

Finish ==
    /\ phase = "finish" /\ active' = active - 1 /\ phase' = "done"
    /\ firstDisplayed' = IF round = 1 THEN displayed ELSE firstDisplayed
    /\ firstAge' = IF round = 1 THEN age ELSE firstAge
    /\ UNCHANGED <<kind, initialAge, response, displayed, validator, age,
                   beforeDisplayed, beforeValidator, beforeAge, round,
                   skipped, requests, conditional, bodyReads, failures>>

Retry ==
    /\ phase = "done" /\ round = 1 /\ round' = 2 /\ phase' = "idle"
    /\ response' = "ok" /\ age' = 2 /\ requests' = 0 /\ skipped' = 0
    /\ bodyReads' = 0 /\ failures' = 0
    /\ UNCHANGED <<kind, initialAge, displayed, validator, beforeDisplayed,
                   beforeValidator, beforeAge, firstDisplayed,
                   firstAge, active, conditional>>

Next == Start \/ Download \/ Overlap \/ Finish \/ Retry
Spec == Init /\ [][Next]_variables
FairSpec == Spec /\ WF_variables(Start)
                 /\ WF_variables(Download) /\ WF_variables(Finish)
                 /\ WF_variables(Retry)
TypeOK == /\ kind \in Kinds /\ response \in Responses
          /\ displayed \in {0, 1} /\ validator \in {0, 1}
          /\ age \in 0..2 /\ round \in {1, 2} /\ active \in {0, 1}
          /\ requests \in 0..1 /\ skipped \in {0, 1}
          /\ conditional \in BOOLEAN
          /\ bodyReads \in 0..1 /\ failures \in 0..1
SingleRefresh == active = IF phase \in {"get", "finish"} THEN 1 ELSE 0
SingleRequest == phase = "done" => requests = 1
ConditionalRequiresValidator ==
    phase \in {"get", "finish", "done"} =>
        conditional = (kind \in {"strong", "unchanged"} \/
                       (kind = "weak" /\ beforeAge < 2))
ValidatorsDescribeDisplay == validator = displayed
FailurePreservesSnapshot ==
    phase = "done" /\ Failure =>
        displayed = beforeDisplayed /\ validator = beforeValidator /\ age = beforeAge
NotModifiedPreservesSnapshot ==
    phase = "done" /\ NotModified =>
        displayed = beforeDisplayed /\ validator = beforeValidator /\ age = beforeAge
NotModifiedReadsNoBody == phase = "done" /\ NotModified => bodyReads = 0
ExpiredWeakCannotSuppress ==
    phase = "done" /\ response = "ok" /\ beforeAge = 2 => displayed = Server
EventuallyCurrent == <>(round = 2 /\ phase = "done" /\ displayed = Server)
=============================================================================
