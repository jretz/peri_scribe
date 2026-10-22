---------------------------- MODULE StageProcesses ----------------------------
EXTENDS Naturals, Sequences

CONSTANT StageCount
Stages == 1..StageCount
VARIABLES parent, child, parentLease, childLease, segment, nextStage,
          completed, pending, required, response, outcome, competitor
variables == <<parent, child, parentLease, childLease, segment, nextStage,
               completed, pending, required, response, outcome, competitor>>
Limit == IF segment = 1 THEN 1 ELSE StageCount
Suffix(first) == [index \in 1..(StageCount - first + 1) |-> first + index - 1]

Init ==
    /\ parent = "new" /\ child = "none"
    /\ parentLease = FALSE /\ childLease = FALSE /\ competitor = FALSE
    /\ segment = 1 /\ nextStage = 1 /\ completed = <<>>
    /\ required \in BOOLEAN
    /\ pending = IF required THEN Suffix(1) ELSE <<>>
    /\ response = "none" /\ outcome = "pending"

Acquire ==
    /\ parent = "new" /\ ~competitor
    /\ parent' = "active" /\ parentLease' = TRUE
    /\ UNCHANGED <<child, childLease, segment, nextStage, completed, pending,
                   required, response, outcome, competitor>>

Compete ==
    /\ ~parentLease /\ ~childLease /\ ~competitor
    /\ competitor' = TRUE
    /\ UNCHANGED <<parent, child, parentLease, childLease, segment, nextStage,
                   completed, pending, required, response, outcome>>
CompetitorExit ==
    /\ competitor /\ competitor' = FALSE
    /\ UNCHANGED <<parent, child, parentLease, childLease, segment, nextStage,
                   completed, pending, required, response, outcome>>

Launch ==
    /\ parent = "active" /\ child = "none" /\ parentLease
    /\ child' = "running" /\ childLease' = TRUE
    /\ UNCHANGED <<parent, parentLease, segment, nextStage, completed, pending,
                   required, response, outcome, competitor>>
LaunchFailure ==
    /\ parent = "active" /\ child = "none"
    /\ parent' = "joining" /\ outcome' = "error"
    /\ UNCHANGED <<child, parentLease, childLease, segment, nextStage, completed,
                   pending, required, response, competitor>>

CompleteStage ==
    /\ child = "running" /\ nextStage <= Limit
    /\ completed' = Append(completed, nextStage)
    /\ pending' = IF pending = <<>> THEN pending ELSE Tail(pending)
    /\ nextStage' = nextStage + 1
    /\ UNCHANGED <<parent, child, parentLease, childLease, segment,
                   required, response, outcome, competitor>>
ChildSuccess ==
    /\ child = "running" /\ nextStage > Limit
    /\ child' = "stopped" /\ childLease' = FALSE
    /\ response' = IF segment = 1 THEN "continue" ELSE "complete"
    /\ UNCHANGED <<parent, parentLease, segment, nextStage, completed, pending,
                   required, outcome, competitor>>
Skip ==
    /\ child = "running" /\ segment = 1 /\ nextStage = 1 /\ ~required
    /\ child' = "stopped" /\ childLease' = FALSE /\ response' = "skip"
    /\ UNCHANGED <<parent, parentLease, segment, nextStage, completed, pending,
                   required, outcome, competitor>>
ChildFailure ==
    /\ child = "running"
    /\ child' = "stopped" /\ childLease' = FALSE /\ response' = "invalid"
    /\ UNCHANGED <<parent, parentLease, segment, nextStage, completed, pending,
                   required, outcome, competitor>>

Continue ==
    /\ parent = "active" /\ child = "stopped" /\ response = "continue"
    /\ segment = 1 /\ nextStage = 2
    /\ segment' = 2 /\ child' = "none" /\ response' = "none"
    /\ UNCHANGED <<parent, parentLease, childLease, nextStage, completed,
                   pending, required, outcome, competitor>>
Finish ==
    /\ parent = "active" /\ child = "stopped"
    /\ response \in {"complete", "skip", "invalid"}
    /\ parent' = "joining"
    /\ outcome' = IF response = "invalid" THEN "error" ELSE "success"
    /\ UNCHANGED <<child, parentLease, childLease, segment, nextStage, completed,
                   pending, required, response, competitor>>
Cancel ==
    /\ parent = "active"
    /\ parent' = "joining" /\ outcome' = "cancelled"
    /\ UNCHANGED <<child, parentLease, childLease, segment, nextStage, completed,
                   pending, required, response, competitor>>
Settle ==
    /\ parent = "joining" /\ child = "running"
    /\ child' = "stopped" /\ childLease' = FALSE /\ response' = "invalid"
    /\ UNCHANGED <<parent, parentLease, segment, nextStage, completed, pending,
                   required, outcome, competitor>>
Release ==
    /\ parent = "joining" /\ child # "running"
    /\ parent' = "released" /\ parentLease' = FALSE
    /\ UNCHANGED <<child, childLease, segment, nextStage, completed, pending,
                   required, response, outcome, competitor>>
ParentCrash ==
    /\ parent \in {"active", "joining"}
    /\ parent' = "dead" /\ parentLease' = FALSE /\ outcome' = "crashed"
    /\ UNCHANGED <<child, childLease, segment, nextStage, completed, pending,
                   required, response, competitor>>

Next == Acquire \/ Compete \/ CompetitorExit \/ Launch \/ LaunchFailure
        \/ CompleteStage \/ ChildSuccess \/ Skip \/ ChildFailure \/ Continue
        \/ Finish \/ Cancel \/ Settle \/ Release \/ ParentCrash
Spec == Init /\ [][Next]_variables

TypeOK ==
    /\ parent \in {"new", "active", "joining", "released", "dead"}
    /\ child \in {"none", "running", "stopped"}
    /\ parentLease \in BOOLEAN /\ childLease \in BOOLEAN
    /\ competitor \in BOOLEAN /\ required \in BOOLEAN
    /\ segment \in {1, 2} /\ nextStage \in 1..(StageCount + 1)
    /\ completed \in Seq(Stages) /\ pending \in Seq(Stages)
    /\ response \in {"none", "continue", "complete", "skip", "invalid"}
    /\ outcome \in {"pending", "success", "error", "cancelled", "crashed"}
WriterExclusion == competitor => (~parentLease /\ ~childLease)
ActiveWorkProtected == child = "running" => childLease
ContinuousParentLease == parent \in {"active", "joining"} => parentLease
JoinedBeforeRelease == parent = "released" => child # "running"
StageOrder == completed = [index \in 1..Len(completed) |-> index]
NoLostPending == required => pending = Suffix(Len(completed) + 1)
HandoffAfterGeography == segment = 2 => Len(completed) >= 1
SuccessfulCompletion == outcome = "success" =>
    (completed = Suffix(1) \/ (~required /\ completed = <<>>))
NoWorkAfterReturn == [][parent = "released" => UNCHANGED completed]_variables
=============================================================================
