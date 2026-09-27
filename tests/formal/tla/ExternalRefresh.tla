--------------------------- MODULE ExternalRefresh ---------------------------
EXTENDS Naturals

CONSTANTS RefreshCount, MaximumCrashes
Snapshots == {"missing", "empty", "features A", "features B"}
Responses == {"error", "empty", "features A", "features B"}
Phases == {"query", "compare", "write", "replace", "cleanup", "done"}
Outcomes == {"none", "kept cache", "raised retrieval", "unchanged", "published",
             "raised write"}

VARIABLES stored, before, temporary, phase, evacuation, response, refresh,
          crashes, outcome, replacements, previousReplacements, replaced
variables == <<stored, before, temporary, phase, evacuation, response, refresh,
               crashes, outcome, replacements, previousReplacements, replaced>>

Init ==
    /\ stored \in Snapshots
    /\ before = stored
    /\ temporary = "missing"
    /\ phase = "query"
    /\ evacuation \in BOOLEAN
    /\ response \in Responses
    /\ refresh = 1
    /\ crashes = MaximumCrashes
    /\ outcome = "none"
    /\ replacements = 0
    /\ previousReplacements = 0
    /\ replaced = FALSE

RetrievalFailed == response = "error" \/ (response = "empty" /\ ~evacuation)

Query ==
    /\ phase = "query"
    /\ phase' = IF RetrievalFailed THEN "done" ELSE "compare"
    /\ outcome' = IF ~RetrievalFailed THEN "none"
                   ELSE IF stored = "missing" THEN "raised retrieval"
                   ELSE "kept cache"
    /\ UNCHANGED <<stored, before, temporary, evacuation, response, refresh,
                   crashes, replacements, previousReplacements, replaced>>

Compare ==
    /\ phase = "compare"
    /\ phase' = IF stored = response THEN "done" ELSE "write"
    /\ outcome' = IF stored = response THEN "unchanged" ELSE "none"
    /\ UNCHANGED <<stored, before, temporary, evacuation, response, refresh,
                   crashes, replacements, previousReplacements, replaced>>

WriteTemporary ==
    /\ phase = "write"
    /\ temporary' = response
    /\ phase' = "replace"
    /\ UNCHANGED <<stored, before, evacuation, response, refresh, crashes,
                   outcome, replacements, previousReplacements, replaced>>

Replace ==
    /\ phase = "replace"
    /\ stored' = temporary
    /\ temporary' = "missing"
    /\ replacements' = replacements + 1
    /\ replaced' = TRUE
    /\ phase' = "cleanup"
    /\ UNCHANGED <<before, evacuation, response, refresh, crashes, outcome,
                   previousReplacements>>

Cleanup ==
    /\ phase = "cleanup"
    /\ phase' = "done"
    /\ outcome' = "published"
    /\ UNCHANGED <<stored, before, temporary, evacuation, response, refresh,
                   crashes, replacements, previousReplacements, replaced>>

\* Retrieval fallback does not swallow failures while writing or replacing a file.
WriteFailure ==
    /\ phase \in {"write", "replace"}
    /\ temporary' = "missing"
    /\ phase' = "done"
    /\ outcome' = "raised write"
    /\ UNCHANGED <<stored, before, evacuation, response, refresh, crashes,
                   replacements, previousReplacements, replaced>>

Crash ==
    /\ phase # "done"
    /\ crashes > 0
    /\ crashes' = crashes - 1
    /\ phase' = "query"
    /\ before' = stored
    /\ previousReplacements' = replacements
    /\ replaced' = FALSE
    /\ outcome' = "none"
    /\ UNCHANGED <<stored, temporary, evacuation, response, refresh, replacements>>

NextRefresh(nextResponse) ==
    /\ phase = "done"
    /\ refresh < RefreshCount
    /\ refresh' = refresh + 1
    /\ phase' = "query"
    /\ response' = nextResponse
    /\ before' = stored
    /\ previousReplacements' = replacements
    /\ replaced' = FALSE
    /\ outcome' = "none"
    /\ UNCHANGED <<stored, temporary, evacuation, crashes, replacements>>

Next == Query \/ Compare \/ WriteTemporary \/ Replace \/ Cleanup \/ WriteFailure
        \/ Crash \/ (\E nextResponse \in Responses: NextRefresh(nextResponse))
Spec == Init /\ [][Next]_variables

TypeOK ==
    /\ stored \in Snapshots /\ before \in Snapshots /\ temporary \in Snapshots
    /\ phase \in Phases /\ evacuation \in BOOLEAN /\ response \in Responses
    /\ refresh \in 1..RefreshCount /\ crashes \in 0..MaximumCrashes
    /\ outcome \in Outcomes
    /\ replacements \in 0..(RefreshCount + MaximumCrashes)
    /\ previousReplacements \in 0..(RefreshCount + MaximumCrashes)
    /\ replaced \in BOOLEAN
RetrievalFailurePreservesCache ==
    outcome \in {"kept cache", "raised retrieval"} =>
        stored = before /\ replacements = previousReplacements
NoCacheRaisesRetrievalFailure ==
    outcome = "raised retrieval" <=> (phase = "done" /\ RetrievalFailed
                                       /\ before = "missing")
OnlyEvacuationsPublishEmpty == outcome = "published" /\ stored = "empty" => evacuation
EqualDigestNeverReplaces ==
    outcome = "unchanged" => stored = before /\ replacements = previousReplacements
UnpublishedWritePreservesOld ==
    phase \in {"write", "replace"} \/ outcome = "raised write" => stored = before
SuccessfulReturnHasData ==
    outcome \in {"kept cache", "unchanged", "published"} => stored # "missing"
ReplacementChangesDigest ==
    replaced => stored # before /\ stored = response
                /\ replacements = previousReplacements + 1
=============================================================================
