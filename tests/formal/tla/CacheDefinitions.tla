--------------------------- MODULE CacheDefinitions ---------------------------
EXTENDS Integers, Sequences, FiniteSets

Keys == {1, 2, 3}
Rows(generation) == IF generation = 1 THEN <<1, 2>> ELSE <<3, 2>>
Members(sequence) == {sequence[index] : index \in DOMAIN sequence}
Required(generation) == IF generation = 0 THEN {} ELSE Members(Rows(generation))
Selected(generation, requested) ==
    SelectSeq(Rows(generation), LAMBDA key: key \in requested)

\* <<0>> means fall back to the authoritative artifact; <<>> is a valid empty selection.
Read(generation, payloads, damaged, requested, artifact, contextMatches, forced,
     validManifest) ==
    IF forced \/ ~contextMatches \/ ~validManifest \/ generation # artifact
    THEN <<0>>
    ELSE IF Required(generation) \cap requested \subseteq payloads \ {damaged}
         THEN Selected(generation, requested)
         ELSE <<0>>
=============================================================================
