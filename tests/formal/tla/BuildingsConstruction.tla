------------------------ MODULE BuildingsConstruction -------------------------
EXTENDS Naturals, FiniteSets, Sequences
CONSTANTS Workers, Limit
VARIABLES phase, worker, appended, aborting, temporary, output, previous,
          valid, fault, badWorker, phases
variables == <<phase, worker, appended, aborting, temporary, output, previous,
               valid, fault, badWorker, phases>>
Active == {w \in Workers : worker[w] \in {"working", "writing"}}
Quiescent == Active = {}
Complete == \A w \in Workers : worker[w] = "done"
Terminal == phase = "cached" \/ (phase \in {"done", "failed"} /\ ~temporary)
Init ==
    /\ previous \in {"absent", "invalid", "valid"} /\ output = previous
    /\ fault \in {"none", "archive", "cancel", "build", "validate", "publish"}
    /\ badWorker \in Workers
    /\ worker = [w \in Workers |-> "waiting"]
    /\ appended = {} /\ aborting = FALSE /\ valid = FALSE /\ phases = <<>>
    /\ phase = IF previous = "valid" THEN "cached" ELSE "collect"
    /\ temporary = (phase = "collect")
Start(w) ==
    /\ phase = "collect" /\ ~aborting /\ worker[w] = "waiting"
    /\ Cardinality(Active) < Limit
    /\ worker' = [worker EXCEPT ![w] = "working"]
    /\ UNCHANGED <<phase, appended, aborting, temporary, output, previous,
                   valid, fault, badWorker, phases>>
BeginAppend(w) ==
    /\ worker[w] = "working" /\ w \notin appended /\ ~aborting
    /\ worker' = [worker EXCEPT ![w] = "writing"]
    /\ UNCHANGED <<phase, appended, aborting, temporary, output, previous,
                   valid, fault, badWorker, phases>>
FinishAppend(w) ==
    /\ worker[w] = "writing" /\ appended' = appended \cup {w}
    /\ worker' = [worker EXCEPT ![w] = "working"]
    /\ UNCHANGED <<phase, aborting, temporary, output, previous,
                   valid, fault, badWorker, phases>>
FinishWorker(w) ==
    /\ worker[w] = "working" /\ (w \in appended \/ aborting)
    /\ ~(fault = "archive" /\ w = badWorker /\ ~aborting)
    /\ worker' = [worker EXCEPT ![w] = IF aborting THEN "cancelled" ELSE "done"]
    /\ UNCHANGED <<phase, appended, aborting, temporary, output, previous,
                   valid, fault, badWorker, phases>>
ArchiveFailure(w) ==
    /\ phase = "collect" /\ ~aborting
    /\ fault = "archive" /\ w = badWorker /\ worker[w] = "working"
    /\ worker' = [worker EXCEPT ![w] = "failed"]
    /\ UNCHANGED <<phase, appended, aborting, temporary, output, previous,
                   valid, fault, badWorker, phases>>
\* Semaphore release can admit a queued worker before TaskGroup notices failure.
NoticeFailure ==
    /\ phase = "collect" /\ ~aborting
    /\ \E w \in Workers : worker[w] = "failed"
    /\ aborting' = TRUE
    /\ UNCHANGED <<phase, worker, appended, temporary, output, previous,
                   valid, fault, badWorker, phases>>
Cancel ==
    /\ phase = "collect" /\ fault = "cancel" /\ ~aborting /\ aborting' = TRUE
    /\ UNCHANGED <<phase, worker, appended, temporary, output, previous,
                   valid, fault, badWorker, phases>>
CancelWaiting(w) ==
    /\ aborting /\ worker[w] = "waiting"
    /\ worker' = [worker EXCEPT ![w] = "cancelled"]
    /\ UNCHANGED <<phase, appended, aborting, temporary, output, previous,
                   valid, fault, badWorker, phases>>
Collected ==
    /\ phase = "collect" /\ Complete /\ ~aborting /\ fault # "cancel"
    /\ phase' = "build"
    /\ phases' = Append(phases, "build")
    /\ UNCHANGED <<worker, appended, aborting, temporary, output, previous,
                   valid, fault, badWorker>>
Aborted ==
    /\ phase = "collect" /\ aborting /\ Quiescent
    /\ \A w \in Workers : worker[w] # "waiting"
    /\ phase' = "failed"
    /\ UNCHANGED <<worker, appended, aborting, temporary, output, previous,
                   valid, fault, badWorker, phases>>
Build ==
    /\ phase = "build" /\ phase' = IF fault = "build" THEN "failed" ELSE "validate"
    /\ phases' = IF fault # "build" THEN Append(phases, "validate") ELSE phases
    /\ UNCHANGED <<worker, appended, aborting, temporary, output, previous,
                   valid, fault, badWorker>>
Validate ==
    /\ phase = "validate" /\ valid' = (fault # "validate")
    /\ phase' = IF fault = "validate" THEN "failed" ELSE "publish"
    /\ phases' = IF fault # "validate" THEN Append(phases, "publish") ELSE phases
    /\ UNCHANGED <<worker, appended, aborting, temporary, output, previous,
                   fault, badWorker>>
Publish ==
    /\ phase = "publish" /\ phase' = IF fault = "publish" THEN "failed" ELSE "done"
    /\ output' = IF fault = "publish" THEN output ELSE "new"
    /\ UNCHANGED <<worker, appended, aborting, temporary, previous,
                   valid, fault, badWorker, phases>>
Cleanup ==
    /\ phase \in {"done", "failed"} /\ temporary /\ Quiescent /\ temporary' = FALSE
    /\ UNCHANGED <<phase, worker, appended, aborting, output, previous,
                   valid, fault, badWorker, phases>>
Next == (\E w \in Workers : Start(w) \/ BeginAppend(w) \/ FinishAppend(w) \/
          FinishWorker(w) \/ ArchiveFailure(w) \/ CancelWaiting(w)) \/
        NoticeFailure \/ Cancel \/ Collected \/ Aborted \/ Build \/ Validate \/
        Publish \/ Cleanup
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ (\A w \in Workers :
    WF_variables(Start(w)) /\ WF_variables(BeginAppend(w)) /\
    WF_variables(FinishAppend(w)) /\ WF_variables(FinishWorker(w)) /\
    WF_variables(ArchiveFailure(w)) /\ WF_variables(CancelWaiting(w))) /\
    WF_variables(NoticeFailure) /\ WF_variables(Cancel) /\
    WF_variables(Collected) /\ WF_variables(Aborted) /\
    WF_variables(Build) /\ WF_variables(Validate) /\ WF_variables(Publish) /\
    WF_variables(Cleanup)
TypeOK ==
    /\ phase \in {"cached", "collect", "build", "validate", "publish", "done", "failed"}
    /\ worker \in [Workers -> {"waiting", "working", "writing", "done",
                               "cancelled", "failed"}]
    /\ appended \subseteq Workers /\ aborting \in BOOLEAN /\ temporary \in BOOLEAN
    /\ valid \in BOOLEAN /\ output \in {"absent", "invalid", "valid", "new"}
    /\ previous \in {"absent", "invalid", "valid"}
    /\ fault \in {"none", "archive", "cancel", "build", "validate", "publish"}
    /\ badWorker \in Workers
    /\ phases \in {<<>>, <<"build">>, <<"build", "validate">>,
                       <<"build", "validate", "publish">>}
BoundedWorkers == Cardinality(Active) <= Limit
WorkersRetainStaging == ~Quiescent => temporary /\ phase = "collect"
BuildOnlyComplete == phase \in {"build", "validate", "publish", "done"} =>
    Complete /\ appended = Workers /\ ~aborting
PublishedOnlyComplete == output = "new" => valid /\ Complete /\ appended = Workers
FailurePreservesPrevious == phase = "failed" => output = previous
CachedPreserved == previous = "valid" => phase = "cached" /\ output = previous
EventuallyFinished == <>Terminal
=============================================================================
