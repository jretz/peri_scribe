------------------------------ MODULE LogReaders ------------------------------
EXTENDS Naturals, Sequences

CONSTANTS MaximumFailures, MaximumReads
VARIABLES plain, archive, receipt, source, base, target, staged, expected,
          phase, failures, late, owner, reading, selectedArchive, selectedPlain,
          observed, snapshot, delivered, completed, seenArchive, retained, cursor,
          needsReplay
rotationVariables == <<plain, archive, receipt, source, base, target, staged,
                       expected, phase, failures, late>>
readerVariables == <<owner, reading, selectedArchive, selectedPlain, observed,
                     snapshot, delivered, completed, seenArchive, retained, cursor,
                     needsReplay>>
variables == <<rotationVariables, readerVariables>>
Rotation == INSTANCE LogRotation

Init ==
    /\ Rotation!Init
    /\ owner = "none" /\ reading = "idle"
    /\ selectedArchive = <<>> /\ selectedPlain = <<>> /\ observed = <<>>
    /\ snapshot = <<>> /\ delivered = <<>> /\ completed = 0
    /\ seenArchive = <<>> /\ retained = <<>> /\ cursor = 0 /\ needsReplay = FALSE
AcquireWriter ==
    /\ owner = "none" /\ phase # "idle"
    /\ owner' = "writer"
    /\ UNCHANGED <<rotationVariables, reading, selectedArchive, selectedPlain,
                   observed, snapshot, delivered, completed, seenArchive, retained,
                   cursor, needsReplay>>
Write ==
    /\ owner = "writer" /\ phase # "idle" /\ Rotation!Progress
    /\ UNCHANGED readerVariables
ReleaseWriter ==
    /\ owner = "writer" /\ phase = "idle" /\ owner' = "none"
    /\ UNCHANGED <<rotationVariables, reading, selectedArchive, selectedPlain,
                   observed, snapshot, delivered, completed, seenArchive, retained,
                   cursor, needsReplay>>
CrashWriter ==
    /\ owner = "writer" /\ Rotation!Crash /\ owner' = "none"
    /\ UNCHANGED <<reading, selectedArchive, selectedPlain, observed,
                   snapshot, delivered, completed, seenArchive, retained, cursor,
                   needsReplay>>
AcquireReader ==
    /\ owner = "none" /\ completed < MaximumReads
    /\ owner' = "reader" /\ reading' = "reset" /\ snapshot' = expected
    /\ needsReplay' \in IF archive # seenArchive THEN {TRUE} ELSE BOOLEAN
    /\ selectedArchive' = archive
    /\ selectedPlain' = IF receipt /\ archive = target THEN <<>> ELSE plain
    /\ observed' = <<>>
    /\ UNCHANGED <<rotationVariables, delivered, completed, seenArchive,
                   retained, cursor>>
ResetReader ==
    /\ owner = "reader" /\ reading = "reset" /\ reading' = "archive"
    /\ retained' = IF needsReplay THEN <<>> ELSE retained
    /\ cursor' = IF needsReplay THEN 0 ELSE cursor
    /\ UNCHANGED <<rotationVariables, owner, selectedArchive, selectedPlain,
                   observed, snapshot, delivered, completed, seenArchive, needsReplay>>
ReadArchive ==
    /\ owner = "reader" /\ reading = "archive"
    /\ retained' = IF needsReplay THEN selectedArchive ELSE retained
    /\ seenArchive' = selectedArchive /\ reading' = "plain"
    /\ UNCHANGED <<rotationVariables, owner, selectedArchive, selectedPlain,
                   observed, snapshot, delivered, completed, cursor, needsReplay>>
ReadPlain ==
    /\ owner = "reader" /\ reading = "plain"
    /\ IF cursor < Len(selectedPlain)
        THEN /\ retained' = Append(retained, selectedPlain[cursor + 1])
             /\ cursor' = cursor + 1 /\ UNCHANGED <<observed, reading>>
        ELSE /\ observed' = retained /\ reading' = "release"
             /\ UNCHANGED <<retained, cursor>>
    /\ UNCHANGED <<rotationVariables, owner, selectedArchive, selectedPlain,
                   snapshot, delivered, completed, seenArchive, needsReplay>>
ReleaseReader ==
    /\ owner = "reader" /\ reading = "release"
    /\ delivered' = observed /\ completed' = completed + 1
    /\ reading' = "idle" /\ owner' = "none"
    /\ UNCHANGED <<rotationVariables, selectedArchive, selectedPlain,
                   observed, snapshot, seenArchive, retained, cursor, needsReplay>>
AppendLate ==
    /\ owner = "none" /\ Rotation!AppendLate
    /\ UNCHANGED readerVariables
WriterProgress == AcquireWriter \/ Write \/ ReleaseWriter \/ AppendLate
ReaderProgress == AcquireReader \/ ResetReader \/ ReadArchive \/ ReadPlain
                  \/ ReleaseReader
Next == WriterProgress \/ ReaderProgress \/ CrashWriter
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(WriterProgress) /\ WF_variables(ReaderProgress)
TypeOK ==
    /\ Rotation!TypeOK
    /\ owner \in {"none", "writer", "reader"}
    /\ reading \in {"idle", "reset", "archive", "plain", "release"}
    /\ completed \in 0..MaximumReads
    /\ selectedArchive \in Seq({1, 2}) /\ selectedPlain \in Seq({1, 2})
    /\ observed \in Seq({1, 2}) /\ snapshot \in Seq({1, 2})
    /\ delivered \in Seq({1, 2}) /\ retained \in Seq({1, 2})
    /\ seenArchive \in Seq({1, 2}) /\ cursor \in 0..2 /\ needsReplay \in BOOLEAN
NoLossOrDuplication == Rotation!NoLossOrDuplication
CoherentSelection == owner = "reader" =>
    selectedArchive \o selectedPlain = snapshot /\ snapshot = expected
CompleteObservation == reading = "release" => observed = snapshot
ReadersNeverMutate == owner = "reader" => Rotation!LogicalContents = expected
EveryDeliveredOccurrence == completed > 0 =>
    delivered \in {<<1, 1>>, <<1, 1, 1>>, <<2, 1, 1>>, <<2, 1, 1, 1>>}
EventuallyRead == <> (completed = MaximumReads)
EventuallyArchived == Rotation!EventuallyArchived
=============================================================================
