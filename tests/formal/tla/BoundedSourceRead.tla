-------------------------- MODULE BoundedSourceRead --------------------------
EXTENDS Naturals, FiniteSets

CONSTANT Blocks
VARIABLES phase, revision, pinned, bad, checked, complete, running, published, validatedRevision
variables == <<phase, revision, pinned, bad, checked, complete, running, published, validatedRevision>>

Init ==
    /\ phase = "closed" /\ revision = 0 /\ pinned = 0
    /\ bad = {} /\ checked = {} /\ complete = {} /\ running = {}
    /\ published = FALSE /\ validatedRevision = 2

Pin ==
    /\ phase = "closed"
    /\ phase' = "metadata" /\ pinned' = revision
    /\ UNCHANGED <<revision, bad, checked, complete, running, published, validatedRevision>>

Metadata ==
    /\ phase = "metadata" /\ phase' = "ownership"
    /\ UNCHANGED <<revision, pinned, bad, checked, complete, running, published, validatedRevision>>

Ownership ==
    /\ phase = "ownership" /\ phase' = "work"
    /\ UNCHANGED <<revision, pinned, bad, checked, complete, running, published, validatedRevision>>

Admit(block) ==
    /\ phase = "work" /\ block \notin running \cup complete
    /\ Cardinality(running) < 2
    /\ running' = running \cup {block}
    /\ UNCHANGED <<phase, revision, pinned, bad, checked, complete, published, validatedRevision>>

Verify(block) ==
    /\ phase = "work" /\ block \in running /\ block \notin bad
    /\ checked' = checked \cup {block}
    /\ UNCHANGED <<phase, revision, pinned, bad, complete, running, published, validatedRevision>>

Finish(block) ==
    /\ phase = "work" /\ block \in running \cap checked
    /\ running' = running \ {block} /\ complete' = complete \cup {block}
    /\ UNCHANGED <<phase, revision, pinned, bad, checked, published, validatedRevision>>

Poison(block) ==
    /\ phase = "closed" /\ block \notin bad
    /\ bad' = bad \cup {block}
    /\ UNCHANGED <<phase, revision, pinned, checked, complete, running, published, validatedRevision>>

Edit ==
    /\ revision = 0
    /\ revision' = 1
    /\ UNCHANGED <<phase, pinned, bad, checked, complete, running, published, validatedRevision>>

Validate ==
    /\ phase = "work" /\ complete = Blocks /\ running = {}
    /\ revision = pinned /\ phase' = "validated" /\ validatedRevision' = pinned
    /\ UNCHANGED <<revision, pinned, bad, checked, complete, running, published>>

Release ==
    /\ phase = "validated" /\ phase' = "released"
    /\ UNCHANGED <<revision, pinned, bad, checked, complete, running, published, validatedRevision>>

Publish ==
    /\ phase = "released" /\ validatedRevision = pinned /\ phase' = "published"
    /\ published' = TRUE
    /\ UNCHANGED <<revision, pinned, bad, checked, complete, running, validatedRevision>>

Abort ==
    /\ phase \in {"metadata", "ownership", "work", "validated", "released"}
    /\ phase' = "aborting"
    /\ UNCHANGED <<revision, pinned, bad, checked, complete, running, published, validatedRevision>>

Settle(block) ==
    /\ phase = "aborting" /\ block \in running
    /\ running' = running \ {block}
    /\ UNCHANGED <<phase, revision, pinned, bad, checked, complete, published, validatedRevision>>

Fallback ==
    /\ phase = "aborting" /\ running = {} /\ phase' = "fallback"
    /\ UNCHANGED <<revision, pinned, bad, checked, complete, running, published, validatedRevision>>

Next == Pin \/ Metadata \/ Ownership \/ Validate \/ Release \/ Publish \/ Edit
    \/ Abort \/ Fallback
    \/ (\E block \in Blocks: Admit(block) \/ Verify(block) \/ Finish(block)
                              \/ Poison(block) \/ Settle(block))
Spec == Init /\ [][Next]_variables

VerifiedBeforeCompletion == complete \subseteq checked /\ checked \cap bad = {}
PublishedComplete == published => complete = Blocks /\ phase = "published"
PublishedValidated == published => validatedRevision = pinned
ReleasedAfterWorkers == phase \in {"released", "published", "fallback"} => running = {}
OwnershipBeforeWork == running # {} => phase \in {"work", "aborting"}
=============================================================================
