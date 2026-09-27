---------------------------- MODULE UpdateJournal ----------------------------
EXTENDS Naturals, FiniteSets

CONSTANTS BatchCount, MaximumFailures
Batches == 1..BatchCount
Phases == {"prepare", "kmz", "publication", "journal", "rotate", "remove plain",
           "publish archive", "forget rotation", "append", "checkpoint", "unlink",
           "viewer", "invalidate publication",
           "done"}

VARIABLES durable, phase, resume, target, baseline, failures, oldMonth, hasRecords
VARIABLE publicationModes
variables == <<durable, phase, resume, target, baseline, failures, oldMonth,
               hasRecords, publicationModes>>

Init ==
    /\ durable = [kmz |-> 0, publication |-> 0, journal |-> 0, checkpoint |-> 0,
                   viewer |-> 0, journalTime |-> 0, rotationReceipt |-> FALSE,
                   rotationTarget |-> [batch \in Batches |-> 0],
                   plain |-> [batch \in Batches |-> 0],
                   archive |-> [batch \in Batches |-> 0],
                   appends |-> [batch \in Batches |-> 0],
                   savedTimes |-> [batch \in Batches |-> 0],
                   loggedTimes |-> [batch \in Batches |-> 0]]
    /\ phase = "prepare"
    /\ resume = "viewer"
    /\ target = 1
    /\ baseline = 0
    /\ failures = MaximumFailures
    /\ oldMonth = FALSE
    /\ hasRecords \in [Batches -> BOOLEAN]
    /\ publicationModes \in [Batches -> [freshInputs: BOOLEAN, gated: BOOLEAN]]

ContainsBatch(batch) == durable.plain[batch] > 0 \/ durable.archive[batch] > 0

\* New inputs cannot be compared while a previous checkpoint needs recovery.
Prepare ==
    /\ phase = "prepare"
    /\ phase' = IF durable.journal = 0 THEN "kmz" ELSE "rotate"
    /\ resume' = "prepare"
    /\ baseline' = durable.checkpoint
    /\ UNCHANGED <<durable, target, failures, oldMonth, hasRecords>>

PublishKmz ==
    /\ phase = "kmz"
    /\ durable' = [durable EXCEPT !.kmz = target]
    /\ phase' = IF publicationModes[target].freshInputs
                THEN "publication" ELSE "journal"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

PublishCheckpoint ==
    /\ phase = "publication"
    /\ publicationModes[target].freshInputs
    /\ durable' = [durable EXCEPT !.publication = target]
    /\ phase' = "journal"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

WriteJournal ==
    /\ phase = "journal"
    /\ IF durable.checkpoint = target
          THEN /\ phase' = "rotate"
               /\ UNCHANGED durable
          ELSE /\ phase' = "rotate"
               /\ durable' = [durable EXCEPT
                      !.journal = target,
                      !.journalTime = MaximumFailures - failures + 1,
                      !.savedTimes[target] = MaximumFailures - failures + 1]
    /\ resume' = "viewer"
    /\ UNCHANGED <<target, baseline, failures, oldMonth, hasRecords>>

\* A receipt precedes archive publication and survives until source retirement.
Rotate ==
    /\ phase = "rotate"
    /\ IF durable.rotationReceipt /\ durable.archive = durable.rotationTarget
          THEN /\ phase' = "remove plain" /\ UNCHANGED durable
          ELSE IF oldMonth /\ (\E batch \in Batches: durable.plain[batch] > 0)
          THEN /\ durable' = [durable EXCEPT !.rotationReceipt = TRUE,
                      !.rotationTarget = [batch \in Batches |->
                          IF durable.archive[batch] > 0
                          THEN durable.archive[batch] ELSE durable.plain[batch]]]
               /\ phase' = "publish archive"
          ELSE /\ UNCHANGED durable
               /\ phase' = "append"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

PublishArchive ==
    /\ phase = "publish archive"
    /\ durable' = [durable EXCEPT !.archive = durable.rotationTarget]
    /\ phase' = "remove plain"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

RemovePlain ==
    /\ phase = "remove plain"
    /\ durable' = [durable EXCEPT !.plain = [batch \in Batches |-> 0]]
    /\ phase' = "forget rotation"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

ForgetRotation ==
    /\ phase = "forget rotation"
    /\ durable' = [durable EXCEPT !.rotationReceipt = FALSE,
                  !.rotationTarget = [batch \in Batches |-> 0]]
    /\ phase' = "append"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

Append ==
    /\ phase = "append"
    \* Unchanged builds still rotate logs but do not create a new journal.
    /\ IF durable.journal = 0
          THEN /\ UNCHANGED durable
               /\ phase' = "viewer"
          ELSE /\ LET batch == durable.journal
                  IN IF hasRecords[batch] /\ ~ContainsBatch(batch)
                        THEN durable' = [durable EXCEPT !.plain[batch] = @ + 1,
                                !.appends[batch] = @ + 1,
                                !.loggedTimes[batch] = durable.journalTime]
                        ELSE UNCHANGED durable
               /\ phase' = "checkpoint"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

Checkpoint ==
    /\ phase = "checkpoint"
    /\ durable' = [durable EXCEPT !.checkpoint = durable.journal]
    /\ phase' = "unlink"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

Unlink ==
    /\ phase = "unlink"
    /\ durable' = [durable EXCEPT !.journal = 0, !.journalTime = 0]
    /\ phase' = resume
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

PublishViewer ==
    /\ phase = "viewer"
    /\ durable' = [durable EXCEPT !.viewer = durable.checkpoint]
    /\ phase' = IF publicationModes[target].gated
                    /\ ~publicationModes[target].freshInputs
                THEN "invalidate publication" ELSE "done"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

\* Gated partial runs discard stale publication evidence after create_kmz returns.
InvalidatePublication ==
    /\ phase = "invalidate publication"
    /\ durable' = [durable EXCEPT !.publication = 0]
    /\ phase' = "done"
    /\ UNCHANGED <<resume, target, baseline, failures, oldMonth, hasRecords>>

NextBatch ==
    /\ phase = "done"
    /\ target < BatchCount
    /\ target' = target + 1
    /\ phase' = "prepare"
    /\ UNCHANGED <<durable, resume, baseline, failures, oldMonth, hasRecords>>

Crash ==
    /\ phase # "done"
    /\ failures > 0
    /\ failures' = failures - 1
    /\ phase' = "prepare"
    /\ resume' = "viewer"
    /\ baseline' = 0
    /\ UNCHANGED <<durable, target, oldMonth, hasRecords>>

AgeLogs ==
    /\ ~oldMonth
    /\ oldMonth' = TRUE
    /\ UNCHANGED <<durable, phase, resume, target, baseline, failures, hasRecords>>

Progress ==
    /\ Prepare \/ PublishKmz \/ PublishCheckpoint \/ WriteJournal \/ Rotate
       \/ PublishArchive \/ RemovePlain \/ ForgetRotation \/ Append
       \/ Checkpoint \/ Unlink \/ PublishViewer
       \/ InvalidatePublication \/ NextBatch
    /\ UNCHANGED publicationModes
Next == (Progress \/ Crash \/ AgeLogs) /\ UNCHANGED publicationModes
Spec == Init /\ [][Next]_variables
FairSpec == Spec /\ WF_variables(Progress)

TypeOK ==
    /\ durable \in [kmz: 0..BatchCount, publication: 0..BatchCount,
         journal: 0..BatchCount, checkpoint: 0..BatchCount, viewer: 0..BatchCount,
         journalTime: 0..(MaximumFailures + 1), rotationReceipt: BOOLEAN,
         rotationTarget: [Batches -> 0..2],
         plain: [Batches -> 0..2], archive: [Batches -> 0..2],
         appends: [Batches -> 0..2],
         savedTimes: [Batches -> 0..(MaximumFailures + 1)],
         loggedTimes: [Batches -> 0..(MaximumFailures + 1)]]
    /\ phase \in Phases
    /\ resume \in {"prepare", "viewer"}
    /\ target \in Batches
    /\ baseline \in 0..BatchCount
    /\ failures \in 0..MaximumFailures
    /\ oldMonth \in BOOLEAN
    /\ hasRecords \in [Batches -> BOOLEAN]
    /\ publicationModes \in [Batches -> [freshInputs: BOOLEAN, gated: BOOLEAN]]

NoRepeatedAppend == \A batch \in Batches: durable.appends[batch] <= 1
CheckpointHasLog ==
    \A batch \in 1..durable.checkpoint: hasRecords[batch] => ContainsBatch(batch)
OriginalTimestampSurvives ==
    \A batch \in Batches:
        ContainsBatch(batch) => durable.loggedTimes[batch] = durable.savedTimes[batch]
AcknowledgmentOrder ==
    durable.viewer <= durable.checkpoint /\ durable.checkpoint <= durable.kmz
    /\ durable.publication <= durable.kmz /\ durable.kmz <= target
PublicationRequiresFreshInputs ==
    durable.publication # 0 => publicationModes[durable.publication].freshInputs
FreshPublicationPrecedesAcknowledgment ==
    publicationModes[target].freshInputs /\ durable.checkpoint = target =>
        durable.publication = target
JournalNeedsCompletedKmz ==
    durable.journal # 0 => durable.checkpoint <= durable.journal
                          /\ durable.journal <= durable.kmz
PreparationUsesRecoveredCheckpoint ==
    phase \in {"kmz", "publication", "journal"} =>
        durable.journal = 0 /\ baseline = durable.checkpoint
CompletedPublicationConsistent ==
    phase = "done" => durable.viewer = target /\ durable.checkpoint = target
                       /\ durable.journal = 0
GatedPartialInvalidatesPublication ==
    phase = "done" /\ publicationModes[target].gated
    /\ ~publicationModes[target].freshInputs => durable.publication = 0
UngatedPartialCannotAcknowledgeFreshInputs ==
    phase = "done" /\ ~publicationModes[target].gated
    /\ ~publicationModes[target].freshInputs => durable.publication < target
EventuallyPublished == <> (phase = "done" /\ target = BatchCount)
=============================================================================
