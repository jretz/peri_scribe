---------------------------- MODULE BrowserRefresh ----------------------------
EXTENDS Naturals

Kinds == {"none", "weak", "strong", "unchanged"}
Responses == {"ok", "head error", "unsupported", "get error", "invalid"}
VARIABLES kind, initialAge, response, phase, displayed, validator, age,
          beforeDisplayed, beforeValidator, beforeAge, round,
          firstDisplayed, firstAge, skipped, requests, active
variables == <<kind, initialAge, response, phase, displayed, validator, age,
               beforeDisplayed, beforeValidator, beforeAge, round,
               firstDisplayed, firstAge, skipped, requests, active>>

Server == IF kind = "unchanged" THEN 0 ELSE 1
Init ==
    /\ kind \in Kinds /\ initialAge \in {0, 2} /\ response \in Responses
    /\ phase = "idle" /\ displayed = 0 /\ validator = 0 /\ age = initialAge
    /\ beforeDisplayed = 0 /\ beforeValidator = 0 /\ beforeAge = initialAge
    /\ round = 1 /\ firstDisplayed = 0
    /\ firstAge = initialAge /\ skipped = 0 /\ requests = 0 /\ active = 0

Start ==
    /\ phase = "idle" /\ phase' = "head" /\ active' = active + 1
    /\ requests' = requests + 1
    /\ beforeDisplayed' = displayed /\ beforeValidator' = validator
    /\ beforeAge' = age
    /\ UNCHANGED <<kind, initialAge, response, displayed, validator, age,
                   round, firstDisplayed, firstAge, skipped>>

Same == kind = "unchanged" \/ (kind = "weak" /\ age < 2)
        \/ (kind = "strong" /\ validator = Server)
Head ==
    /\ phase = "head"
    /\ phase' = IF response = "head error" \/
                     (response # "unsupported" /\ Same) THEN "finish" ELSE "get"
    /\ requests' = requests + IF phase' = "get" THEN 1 ELSE 0
    /\ UNCHANGED <<kind, initialAge, response, displayed, validator, age,
                   beforeDisplayed, beforeValidator, beforeAge, round,
                   firstDisplayed, firstAge, skipped, active>>

Download ==
    /\ phase = "get" /\ phase' = "finish"
    /\ displayed' = IF response \in {"get error", "invalid"}
                     THEN displayed ELSE Server
    /\ validator' = IF response \in {"get error", "invalid"}
                     THEN validator ELSE Server
    /\ age' = IF response \in {"get error", "invalid"} THEN age ELSE 0
    /\ UNCHANGED <<kind, initialAge, response, beforeDisplayed, beforeValidator,
                   beforeAge, round, firstDisplayed, firstAge, skipped,
                   requests, active>>

Overlap ==
    /\ phase \in {"head", "get"} /\ skipped = 0 /\ skipped' = 1
    /\ UNCHANGED <<kind, initialAge, response, phase, displayed, validator, age,
                   beforeDisplayed, beforeValidator, beforeAge, round,
                   firstDisplayed, firstAge, requests, active>>

Finish ==
    /\ phase = "finish" /\ active' = active - 1 /\ phase' = "done"
    /\ firstDisplayed' = IF round = 1 THEN displayed ELSE firstDisplayed
    /\ firstAge' = IF round = 1 THEN age ELSE firstAge
    /\ UNCHANGED <<kind, initialAge, response, displayed, validator, age,
                   beforeDisplayed, beforeValidator, beforeAge, round,
                   skipped, requests>>

Retry ==
    /\ phase = "done" /\ round = 1 /\ round' = 2 /\ phase' = "idle"
    /\ response' = "ok" /\ age' = 2 /\ requests' = 0 /\ skipped' = 0
    /\ UNCHANGED <<kind, initialAge, displayed, validator, beforeDisplayed,
                   beforeValidator, beforeAge, firstDisplayed,
                   firstAge, active>>

Next == Start \/ Head \/ Download \/ Overlap \/ Finish \/ Retry
Spec == Init /\ [][Next]_variables
FairSpec == Spec /\ WF_variables(Start) /\ WF_variables(Head)
                 /\ WF_variables(Download) /\ WF_variables(Finish)
                 /\ WF_variables(Retry)
TypeOK == /\ kind \in Kinds /\ response \in Responses
          /\ displayed \in {0, 1} /\ validator \in {0, 1}
          /\ age \in 0..2 /\ round \in {1, 2} /\ active \in {0, 1}
          /\ requests \in 0..2 /\ skipped \in {0, 1}
SingleRefresh == active = IF phase \in {"head", "get", "finish"} THEN 1 ELSE 0
ValidatorsDescribeDisplay == validator = displayed
FailurePreservesSnapshot ==
    phase = "done" /\ response \in {"head error", "get error", "invalid"} =>
        displayed = beforeDisplayed /\ validator = beforeValidator /\ age = beforeAge
ExpiredWeakCannotSuppress ==
    phase = "done" /\ response = "ok" /\ beforeAge = 2 => displayed = Server
EventuallyCurrent == <>(round = 2 /\ phase = "done" /\ displayed = Server)
=============================================================================
