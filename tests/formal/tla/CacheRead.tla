------------------------------ MODULE CacheRead ------------------------------
EXTENDS CacheDefinitions

VARIABLES generation, payloads, damaged, requested, artifact, contextMatches,
          forced, validManifest, answer
variables == <<generation, payloads, damaged, requested, artifact, contextMatches,
               forced, validManifest, answer>>

Init ==
    /\ generation \in 0..2
    /\ payloads \in SUBSET Keys
    /\ damaged \in 0..3
    /\ requested \in SUBSET Keys
    /\ artifact \in 1..2
    /\ contextMatches \in BOOLEAN
    /\ forced \in BOOLEAN
    /\ validManifest \in BOOLEAN
    /\ answer = Read(generation, payloads, damaged, requested, artifact,
                     contextMatches, forced, validManifest)
Next == FALSE
Spec == Init /\ [][Next]_variables

CacheIsTransparent == answer # <<0>> => answer = Selected(artifact, requested)
MissingRequiredPayloadFallsBack ==
    ~(Required(artifact) \cap requested \subseteq payloads \ {damaged}) =>
        answer = <<0>>
BypassIsRespected == forced \/ ~contextMatches \/ ~validManifest => answer = <<0>>
NoStaleGeneration == generation # artifact => answer = <<0>>
=============================================================================
