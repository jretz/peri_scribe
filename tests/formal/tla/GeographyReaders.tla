-------------------------- MODULE GeographyReaders ---------------------------
EXTENDS Naturals, Sequences

VARIABLES full, differential, fullSignature, differentialSignature, parent,
          writer, writerPhase, reader, readerPhase, tolerant, result
variables == <<full, differential, fullSignature, differentialSignature, parent,
               writer, writerPhase, reader, readerPhase, tolerant, result>>
Init ==
    /\ full \in 0..2 /\ differential \in 0..2
    /\ fullSignature \in 0..2 /\ differentialSignature \in 0..2
    /\ parent = differentialSignature
    /\ writer = FALSE /\ writerPhase = "start"
    /\ reader = FALSE /\ readerPhase = "start"
    /\ tolerant \in BOOLEAN /\ result = <<>>
AcquireWriter ==
    /\ writerPhase = "start" /\ ~reader
    /\ writer' = TRUE /\ writerPhase' = "full"
    /\ UNCHANGED <<full, differential, fullSignature, differentialSignature, parent,
                   reader, readerPhase, tolerant, result>>
WriteFull ==
    /\ writer /\ writerPhase = "full"
    /\ full' = 2 /\ writerPhase' = "fullSignature"
    /\ UNCHANGED <<differential, fullSignature, differentialSignature, parent,
                   writer, reader, readerPhase, tolerant, result>>
SignFull ==
    /\ writer /\ writerPhase = "fullSignature"
    /\ fullSignature' = 2 /\ writerPhase' = "differential"
    /\ UNCHANGED <<full, differential, differentialSignature, parent,
                   writer, reader, readerPhase, tolerant, result>>
WriteDifferential ==
    /\ writer /\ writerPhase = "differential"
    /\ differential' = 2 /\ writerPhase' = "differentialSignature"
    /\ UNCHANGED <<full, fullSignature, differentialSignature, parent,
                   writer, reader, readerPhase, tolerant, result>>
SignDifferential ==
    /\ writer /\ writerPhase = "differentialSignature"
    /\ differentialSignature' = 2 /\ parent' = 2 /\ writerPhase' = "end"
    /\ UNCHANGED <<full, differential, fullSignature, writer, reader,
                   readerPhase, tolerant, result>>
ReleaseWriter ==
    /\ writer /\ writer' = FALSE /\ writerPhase' = "done"
    /\ UNCHANGED <<full, differential, fullSignature, differentialSignature, parent,
                   reader, readerPhase, tolerant, result>>
AcquireReader ==
    /\ readerPhase = "start" /\ ~writer
    /\ reader' = TRUE /\ readerPhase' = "authenticate"
    /\ UNCHANGED <<full, differential, fullSignature, differentialSignature, parent,
                   writer, writerPhase, tolerant, result>>
Authenticate ==
    /\ reader /\ readerPhase = "authenticate"
    /\ readerPhase' =
          IF tolerant /\ full = 0 /\ differential = 0 THEN "empty"
          ELSE IF full # 0 /\ differential # 0 /\ full = fullSignature
                  /\ differential = differentialSignature /\ parent = full
               THEN "read" ELSE "refused"
    /\ UNCHANGED <<full, differential, fullSignature, differentialSignature, parent,
                   writer, writerPhase, reader, tolerant, result>>
Read ==
    /\ reader /\ readerPhase = "read" /\ Len(result) < 4
    /\ result' = Append(result, IF Len(result) < 3 THEN full ELSE differential)
    /\ UNCHANGED <<full, differential, fullSignature, differentialSignature, parent,
                   writer, writerPhase, reader, readerPhase, tolerant>>
Return ==
    /\ reader /\ (readerPhase \in {"empty", "refused"} \/ Len(result) = 4)
    /\ reader' = FALSE /\ readerPhase' = "done"
    /\ UNCHANGED <<full, differential, fullSignature, differentialSignature, parent,
                   writer, writerPhase, tolerant, result>>
Next == AcquireWriter \/ WriteFull \/ SignFull \/ WriteDifferential
        \/ SignDifferential \/ ReleaseWriter \/ AcquireReader \/ Authenticate
        \/ Read \/ Return
Spec == Init /\ [][Next]_variables
TypeOK ==
    /\ full \in 0..2 /\ differential \in 0..2
    /\ fullSignature \in 0..2 /\ differentialSignature \in 0..2 /\ parent \in 0..2
    /\ writer \in BOOLEAN /\ reader \in BOOLEAN /\ tolerant \in BOOLEAN
    /\ writerPhase \in {"start", "full", "fullSignature", "differential",
                         "differentialSignature", "end", "done"}
    /\ readerPhase \in {"start", "authenticate", "empty", "read", "refused", "done"}
    /\ result \in Seq(0..2) /\ Len(result) <= 4
ReaderWriterExclusion == ~(reader /\ writer)
OnlyAuthenticatedReads == Len(result) > 0 =>
    \A index \in DOMAIN result: result[index] # 0
OneGenerationPerResult == Len(result) > 0 =>
    \A index \in DOMAIN result: result[index] = result[1]
=============================================================================
