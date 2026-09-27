------------------------- MODULE BrowserResponsiveness -------------------------
EXTENDS Naturals, Integers, Sequences, FiniteSets

CONSTANT MaximumSteps
Events == {"response", "reject", "advance", "delay", "dispatch"}
VARIABLES clock, lastResponse, deadline, warning, trace
variables == <<clock, lastResponse, deadline, warning, trace>>

Init == /\ clock = 0 /\ lastResponse = -1 /\ deadline = 2
        /\ warning = FALSE /\ trace = <<>>
CanStep == Len(trace) < MaximumSteps
Response ==
    /\ CanStep /\ lastResponse' = clock /\ deadline' = clock + 2
    /\ warning' = FALSE /\ trace' = Append(trace, "response")
    /\ UNCHANGED clock
Reject ==
    /\ CanStep /\ trace' = Append(trace, "reject")
    /\ UNCHANGED <<clock, lastResponse, deadline, warning>>
Advance ==
    /\ CanStep /\ clock' = clock + 1
    /\ warning' = (clock' >= deadline)
    /\ trace' = Append(trace, "advance")
    /\ UNCHANGED <<lastResponse, deadline>>
Delay ==
    /\ CanStep /\ clock' = clock + 1 /\ trace' = Append(trace, "delay")
    /\ UNCHANGED <<lastResponse, deadline, warning>>
Dispatch ==
    /\ CanStep /\ warning' = (clock >= deadline)
    /\ trace' = Append(trace, "dispatch")
    /\ UNCHANGED <<clock, lastResponse, deadline>>

Next == Response \/ Reject \/ Advance \/ Delay \/ Dispatch
Spec == Init /\ [][Next]_variables
TimeAt(index) == Cardinality({step \in 1..index:
    trace[step] \in {"advance", "delay"}})
Responses == {index \in DOMAIN trace: trace[index] = "response"}
LatestResponse == IF Responses = {} THEN 0
                  ELSE CHOOSE latest \in Responses:
                      \A previous \in Responses: latest >= previous
ExpectedResponseTime == IF LatestResponse = 0 THEN -1 ELSE TimeAt(LatestResponse)
ExpectedDeadline == IF LatestResponse = 0 THEN 2 ELSE TimeAt(LatestResponse) + 2
ProcessedSilence == \E index \in (LatestResponse + 1)..Len(trace):
    trace[index] \in {"advance", "dispatch"} /\ TimeAt(index) >= ExpectedDeadline

TypeOK == /\ clock \in 0..MaximumSteps
          /\ lastResponse \in (-1)..MaximumSteps
          /\ deadline \in 2..(MaximumSteps + 2) /\ warning \in BOOLEAN
          /\ trace \in Seq(Events)
ClockMatchesEvents == clock = TimeAt(Len(trace))
OnlyResponsesRenew == lastResponse = ExpectedResponseTime /\ deadline = ExpectedDeadline
NoEarlyWarning == warning => clock >= ExpectedDeadline
WarningMatchesHistory == warning = ProcessedSilence
ResponseClearsImmediately ==
    Len(trace) > 0 /\ trace[Len(trace)] = "response" => ~warning
DispatchedTimerDetectsSilence ==
    Len(trace) > 0 /\ trace[Len(trace)] \in {"advance", "dispatch"} =>
        warning = (clock >= ExpectedDeadline)
=============================================================================
