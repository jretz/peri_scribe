---------------------------- MODULE OrderedWorkers ----------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS TaskCount, PendingLimit, WeightLimit, WorkerLimit
Tasks == 1..TaskCount
VARIABLES status, observed, submitted, delivered, owner, outcome, failed,
          weights, failures, published
variables == <<status, observed, submitted, delivered, owner, outcome, failed,
               weights, failures, published>>

RECURSIVE WeightSum(_)
WeightSum(items) == IF items = {} THEN 0 ELSE
    LET item == CHOOSE member \in items : TRUE
    IN weights[item] + WeightSum(items \ {item})
Pending == (1..submitted) \ observed
Running == {item \in Tasks : status[item] = "running"}
FailedObserved == {item \in observed : status[item] = "bad"}
NextPosition == Len(delivered) + 1

Init ==
    /\ status = [item \in Tasks |-> "new"]
    /\ observed = {} /\ submitted = 0 /\ delivered = <<>>
    /\ owner = "active" /\ outcome = "pending" /\ failed = 0
    /\ weights \in [Tasks -> {0, 1, 3}] /\ failures \in SUBSET Tasks
    /\ published = FALSE

Admit ==
    /\ owner = "active" /\ FailedObserved = {} /\ submitted < TaskCount
    /\ Cardinality(Pending) < PendingLimit
    /\ Pending = {} \/ WeightSum(Pending) + weights[submitted + 1] <= WeightLimit
    /\ submitted' = submitted + 1
    /\ status' = [status EXCEPT ![submitted + 1] = "queued"]
    /\ UNCHANGED <<observed, delivered, owner, outcome, failed, weights,
                   failures, published>>
Start(item) ==
    /\ status[item] = "queued" /\ Cardinality(Running) < WorkerLimit
    /\ status' = [status EXCEPT ![item] = "running"]
    /\ UNCHANGED <<observed, submitted, delivered, owner, outcome, failed,
                   weights, failures, published>>
Finish(item) ==
    /\ status[item] = "running"
    /\ status' = [status EXCEPT ![item] = IF item \in failures THEN "bad" ELSE "good"]
    /\ UNCHANGED <<observed, submitted, delivered, owner, outcome, failed,
                   weights, failures, published>>
Observe(item) ==
    /\ owner = "active" /\ item \in Pending /\ status[item] \in {"good", "bad"}
    /\ observed' = observed \cup {item}
    /\ UNCHANGED <<status, submitted, delivered, owner, outcome, failed,
                   weights, failures, published>>
Deliver ==
    /\ owner = "active" /\ NextPosition \in observed
    /\ status[NextPosition] = "good"
    /\ delivered' = Append(delivered, NextPosition)
    /\ UNCHANGED <<status, observed, submitted, owner, outcome, failed,
                   weights, failures, published>>
Raise ==
    /\ owner = "active" /\ NextPosition \in observed
    /\ status[NextPosition] = "bad"
    /\ owner' = "closing" /\ outcome' = "error" /\ failed' = NextPosition
    /\ UNCHANGED <<status, observed, submitted, delivered, weights,
                   failures, published>>
Complete ==
    /\ owner = "active" /\ Len(delivered) = TaskCount
    /\ owner' = "closing" /\ outcome' = "success"
    /\ UNCHANGED <<status, observed, submitted, delivered, failed, weights,
                   failures, published>>
Cancel ==
    /\ owner = "active"
    /\ owner' = "closing" /\ outcome' = "cancelled"
    /\ UNCHANGED <<status, observed, submitted, delivered, failed, weights,
                   failures, published>>
CancelQueued(item) ==
    /\ owner = "closing" /\ status[item] = "queued"
    /\ status' = [status EXCEPT ![item] = "cancelled"]
    /\ UNCHANGED <<observed, submitted, delivered, owner, outcome, failed,
                   weights, failures, published>>
Release ==
    /\ owner = "closing"
    /\ \A item \in Tasks : status[item] \notin {"queued", "running"}
    /\ owner' = "released"
    /\ UNCHANGED <<status, observed, submitted, delivered, outcome, failed,
                   weights, failures, published>>
Publish ==
    /\ owner = "released" /\ outcome = "success" /\ ~published
    /\ published' = TRUE
    /\ UNCHANGED <<status, observed, submitted, delivered, owner, outcome,
                   failed, weights, failures>>
Next == Admit \/ Deliver \/ Raise \/ Complete \/ Cancel \/ Release \/ Publish
        \/ (\E item \in Tasks : Start(item) \/ Finish(item) \/ Observe(item)
                              \/ CancelQueued(item))
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Admit) /\ WF_variables(Deliver)
    /\ WF_variables(Raise) /\ WF_variables(Complete) /\ WF_variables(Release)
    /\ (\A item \in Tasks : WF_variables(Start(item)) /\ WF_variables(Finish(item))
        /\ WF_variables(Observe(item)) /\ WF_variables(CancelQueued(item)))
TypeOK ==
    /\ status \in [Tasks -> {"new", "queued", "running", "good", "bad", "cancelled"}]
    /\ observed \subseteq 1..submitted /\ submitted \in 0..TaskCount
    /\ delivered \in Seq(Tasks) /\ Len(delivered) <= TaskCount
    /\ owner \in {"active", "closing", "released"}
    /\ outcome \in {"pending", "success", "error", "cancelled"}
    /\ failed \in 0..TaskCount /\ weights \in [Tasks -> {0, 1, 3}]
    /\ failures \subseteq Tasks /\ published \in BOOLEAN
PendingBound == Cardinality(Pending) <= PendingLimit
WeightedBound == WeightSum(Pending) <= WeightLimit \/ Cardinality(Pending) <= 1
WorkerBound == Cardinality(Running) <= WorkerLimit
OrderedResults == \A index \in 1..Len(delivered) : delivered[index] = index
OnlySuccessfulResults == \A index \in 1..Len(delivered) : status[index] = "good"
FirstInputError == outcome = "error" => failed \in failures
    /\ \A earlier \in 1..(failed - 1) : earlier \notin failures
JoinedBeforeRelease == owner = "released" =>
    \A item \in Tasks : status[item] \notin {"queued", "running"}
PublishOnlyComplete == published => owner = "released" /\ outcome = "success"
    /\ Len(delivered) = TaskCount /\ failures = {}
NoAdmissionAfterFailure == [][FailedObserved # {} => submitted' = submitted]_variables
NoDeliveryAfterClosing == [][owner # "active" => delivered' = delivered]_variables
EventuallyReleased == <> (owner = "released")
=============================================================================
