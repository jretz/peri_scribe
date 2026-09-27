--------------------------- MODULE DurableUpdateValidation ---------------------------
EXTENDS Naturals, Sequences, FiniteSets

VARIABLES operation, checkpointKind, journalKind, requestKind, same, hasRecords,
          checkpoint, journal, logged, phase, validated, prepared, effects
variables == <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
               checkpoint, journal, logged, phase, validated, prepared, effects>>

Invalid ==
    \/ checkpointKind = "invalid"
    \/ operation # "view" /\ journalKind = "invalid"
    \/ operation = "write" /\ requestKind = "invalid"

Init ==
    /\ operation \in {"recover", "write", "view"}
    /\ checkpointKind \in {"missing", "valid", "invalid"}
    /\ journalKind \in {"missing", "valid", "invalid"}
    /\ requestKind \in {"valid", "invalid"}
    /\ same \in BOOLEAN /\ hasRecords \in BOOLEAN
    /\ same => checkpointKind = "valid" \/ journalKind = "valid"
    /\ checkpoint = 0
    /\ journal = IF journalKind = "valid" THEN 1 ELSE 0
    /\ logged \in IF hasRecords THEN SUBSET {1} ELSE {{}}
    /\ phase = "validate" /\ validated = FALSE /\ prepared = FALSE /\ effects = <<>>

Validate ==
    /\ phase = "validate"
    /\ phase' = IF Invalid THEN "rejected" ELSE IF operation = "view" THEN "view" ELSE "recover"
    /\ validated' = ~Invalid
    /\ UNCHANGED <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
                   checkpoint, journal, logged, prepared, effects>>
Recover ==
    /\ phase = "recover"
    /\ phase' = IF journal = 0 THEN "prepare" ELSE "append"
    /\ UNCHANGED <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
                   checkpoint, journal, logged, validated, prepared, effects>>
AppendBatch ==
    /\ phase = "append" /\ journal \in {1, 2}
    /\ logged' = IF hasRecords THEN logged \cup {journal} ELSE logged
    /\ effects' = Append(effects, <<"append", journal>>)
    /\ phase' = "acknowledge"
    /\ UNCHANGED <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
                   checkpoint, journal, validated, prepared>>
Acknowledge ==
    /\ phase = "acknowledge"
    /\ checkpoint' = journal /\ phase' = "retire"
    /\ effects' = Append(effects, <<"acknowledge", journal>>)
    /\ UNCHANGED <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
                   journal, logged, validated, prepared>>
Retire ==
    /\ phase = "retire"
    /\ effects' = Append(effects, <<"retire", journal>>)
    /\ journal' = 0 /\ phase' = IF prepared THEN "done" ELSE "prepare"
    /\ UNCHANGED <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
                   checkpoint, logged, validated, prepared>>
Prepare ==
    /\ phase = "prepare"
    /\ phase' = IF operation = "recover" THEN "done" ELSE IF same THEN "rotate" ELSE "publish"
    /\ UNCHANGED <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
                   checkpoint, journal, logged, validated, prepared, effects>>
Publish ==
    /\ phase = "publish"
    /\ journal' = 2 /\ prepared' = TRUE /\ phase' = "append"
    /\ effects' = Append(effects, <<"publish", 2>>)
    /\ UNCHANGED <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
                   checkpoint, logged, validated>>
View ==
    /\ phase = "view"
    /\ phase' = "done" /\ effects' = Append(effects, <<"view", 0>>)
    /\ UNCHANGED <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
                   checkpoint, journal, logged, validated, prepared>>
Rotate ==
    /\ phase = "rotate"
    /\ phase' = "done" /\ effects' = Append(effects, <<"rotate", 0>>)
    /\ UNCHANGED <<operation, checkpointKind, journalKind, requestKind, same, hasRecords,
                   checkpoint, journal, logged, validated, prepared>>
Next == Validate \/ Recover \/ AppendBatch \/ Acknowledge \/ Retire \/ Prepare \/ Publish \/ View \/ Rotate
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Next)

TypeOK ==
    /\ operation \in {"recover", "write", "view"}
    /\ checkpointKind \in {"missing", "valid", "invalid"}
    /\ journalKind \in {"missing", "valid", "invalid"}
    /\ requestKind \in {"valid", "invalid"}
    /\ same \in BOOLEAN /\ hasRecords \in BOOLEAN
    /\ checkpoint \in 0..2 /\ journal \in 0..2 /\ logged \subseteq {1, 2}
    /\ phase \in {"validate", "rejected", "recover", "append", "acknowledge",
                  "retire", "prepare", "publish", "view", "rotate", "done"}
    /\ validated \in BOOLEAN /\ prepared \in BOOLEAN
    /\ effects \in Seq({"append", "acknowledge", "retire", "publish", "view", "rotate"} \X (0..2))
InvalidIntentIsUntouched == Invalid => effects = <<>>
WritesFollowCompleteValidation == Len(effects) > 0 => validated
InvalidCannotSucceed == phase = "done" => ~Invalid
AcknowledgmentFollowsCompleteBatch ==
    checkpoint > 0 /\ hasRecords => checkpoint \in logged
RetirementFollowsAcknowledgment ==
    \A index \in 1..Len(effects) :
        effects[index][1] = "retire" =>
            /\ index > 1
            /\ effects[index - 1] = <<"acknowledge", effects[index][2]>>
ValidationTerminates == <> (phase \in {"done", "rejected"})
=============================================================================
