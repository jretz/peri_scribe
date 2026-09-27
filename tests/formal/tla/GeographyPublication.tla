------------------------ MODULE GeographyPublication ------------------------
EXTENDS Naturals

CONSTANTS GenerationCount, MaximumFailures, InitiallyConsistent
Generations == 0..GenerationCount
Phases == {"check full", "full bytes", "full metadata", "check differential",
           "differential bytes", "differential metadata", "acknowledge", "done"}
Signature(generation) == [checksum |-> generation, generation |-> generation,
                          validVersion |-> TRUE, completeLayers |-> TRUE]
Authenticates(signature, bytes, generation) ==
    signature.validVersion /\ signature.completeLayers
    /\ signature.checksum = bytes /\ signature.generation = generation

VARIABLES fullBytes, differentialBytes, fullSignature, differentialSignature,
          phase, target, failures, forced, pending, reusedFull, reusedDifferential
variables == <<fullBytes, differentialBytes, fullSignature, differentialSignature,
               phase, target, failures, forced, pending, reusedFull,
               reusedDifferential>>

Init ==
    /\ fullBytes \in 0..1
    /\ differentialBytes \in 0..1
    /\ fullSignature \in {[Signature(generation) EXCEPT !.validVersion = version,
                             !.completeLayers = layers]: generation \in 0..1,
                             version \in BOOLEAN, layers \in BOOLEAN}
    /\ differentialSignature \in {
           [Signature(generation) EXCEPT !.validVersion = version,
                !.completeLayers = layers]: generation \in 0..1,
                version \in BOOLEAN, layers \in BOOLEAN}
    /\ InitiallyConsistent =>
           fullBytes = 0 /\ differentialBytes = 0 /\ fullSignature = Signature(0)
           /\ differentialSignature = Signature(0)
    /\ phase = "check full"
    /\ target = 1
    /\ failures = MaximumFailures
    /\ forced \in BOOLEAN
    /\ pending = TRUE
    /\ reusedFull = FALSE
    /\ reusedDifferential = FALSE

CheckFull ==
    /\ phase = "check full"
    /\ reusedFull' = (~forced /\ Authenticates(fullSignature, fullBytes, target))
    /\ phase' = IF reusedFull' THEN "check differential" ELSE "full bytes"
    /\ UNCHANGED <<fullBytes, differentialBytes, fullSignature, differentialSignature,
                   target, failures, forced, pending, reusedDifferential>>

WriteFullBytes ==
    /\ phase = "full bytes"
    /\ fullBytes' = target
    /\ phase' = "full metadata"
    /\ UNCHANGED <<differentialBytes, fullSignature, differentialSignature, target,
                   failures, forced, pending, reusedFull, reusedDifferential>>

WriteFullMetadata ==
    /\ phase = "full metadata"
    /\ fullSignature' = Signature(target)
    /\ phase' = "check differential"
    /\ UNCHANGED <<fullBytes, differentialBytes, differentialSignature, target,
                   failures, forced, pending, reusedFull, reusedDifferential>>

\* Differential generation includes the authenticated full file's checksum.
CheckDifferential ==
    /\ phase = "check differential"
    /\ reusedDifferential' =
           (~forced /\ Authenticates(differentialSignature, differentialBytes,
                                      fullSignature.checksum))
    /\ phase' = IF reusedDifferential' THEN "acknowledge" ELSE "differential bytes"
    /\ UNCHANGED <<fullBytes, differentialBytes, fullSignature, differentialSignature,
                   target, failures, forced, pending, reusedFull>>

WriteDifferentialBytes ==
    /\ phase = "differential bytes"
    /\ differentialBytes' = fullBytes
    /\ phase' = "differential metadata"
    /\ UNCHANGED <<fullBytes, fullSignature, differentialSignature, target,
                   failures, forced, pending, reusedFull, reusedDifferential>>

WriteDifferentialMetadata ==
    /\ phase = "differential metadata"
    /\ differentialSignature' = Signature(fullSignature.checksum)
    /\ phase' = "acknowledge"
    /\ UNCHANGED <<fullBytes, differentialBytes, fullSignature, target,
                   failures, forced, pending, reusedFull, reusedDifferential>>

Acknowledge ==
    /\ phase = "acknowledge"
    /\ pending' = FALSE
    /\ phase' = "done"
    /\ UNCHANGED <<fullBytes, differentialBytes, fullSignature, differentialSignature,
                   target, failures, forced, reusedFull, reusedDifferential>>

NewGeneration ==
    /\ phase = "done"
    /\ target < GenerationCount
    /\ target' = target + 1
    /\ pending' = TRUE
    /\ phase' = "check full"
    /\ reusedFull' = FALSE
    /\ reusedDifferential' = FALSE
    /\ UNCHANGED <<fullBytes, differentialBytes, fullSignature, differentialSignature,
                   failures, forced>>

Crash ==
    /\ phase # "done"
    /\ failures > 0
    /\ failures' = failures - 1
    /\ phase' = "check full"
    /\ reusedFull' = FALSE
    /\ reusedDifferential' = FALSE
    /\ UNCHANGED <<fullBytes, differentialBytes, fullSignature, differentialSignature,
                   target, forced, pending>>

Progress == CheckFull \/ WriteFullBytes \/ WriteFullMetadata \/ CheckDifferential
            \/ WriteDifferentialBytes \/ WriteDifferentialMetadata \/ Acknowledge
            \/ NewGeneration
Next == Progress \/ Crash
Spec == Init /\ [][Next]_variables
FairSpec == Spec /\ WF_variables(Progress)

TypeOK ==
    /\ fullBytes \in Generations
    /\ differentialBytes \in Generations
    /\ fullSignature \in [checksum: Generations, generation: Generations,
                           validVersion: BOOLEAN, completeLayers: BOOLEAN]
    /\ differentialSignature \in [checksum: Generations, generation: Generations,
                                   validVersion: BOOLEAN, completeLayers: BOOLEAN]
    /\ phase \in Phases
    /\ target \in 1..GenerationCount
    /\ failures \in 0..MaximumFailures
    /\ forced \in BOOLEAN
    /\ pending \in BOOLEAN
    /\ reusedFull \in BOOLEAN
    /\ reusedDifferential \in BOOLEAN

AcknowledgedPairMatches == ~pending => fullBytes = target /\ differentialBytes = target
FullReuseAuthenticated ==
    reusedFull => ~forced /\ fullBytes = target
                  /\ Authenticates(fullSignature, fullBytes, target)
DifferentialReuseAuthenticated ==
    reusedDifferential => ~forced /\ differentialBytes = fullBytes
                          /\ Authenticates(differentialSignature, differentialBytes,
                                             fullSignature.checksum)
InterruptedMetadataCannotAuthorizeReuse ==
    fullSignature.checksum # fullBytes => ~reusedFull
PairAlwaysMatches == fullBytes = differentialBytes
EventuallyPublished == <> (phase = "done" /\ target = GenerationCount)
=============================================================================
