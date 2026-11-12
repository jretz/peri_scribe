----------------------------- MODULE JournalReplay -----------------------------
EXTENDS UpdateJournal

\* Retain reachable crash inputs and their uninterrupted recovery outcomes.
VARIABLES recoveryInput, recoveryAge, replaying, recovered
replayVariables == <<variables, recoveryInput, recoveryAge, replaying, recovered>>

ReplayInit ==
    /\ Init
    /\ recoveryInput = durable
    /\ recoveryAge = oldMonth
    /\ replaying = FALSE
    /\ recovered = FALSE

Explore ==
    /\ ~replaying
    /\ Next
    /\ UNCHANGED <<recoveryInput, recoveryAge, replaying, recovered>>

BeginRecovery ==
    /\ ~replaying
    /\ phase = "prepare"
    /\ durable.journal # 0
    /\ recoveryInput' = durable
    /\ recoveryAge' = oldMonth
    /\ replaying' = TRUE
    /\ recovered' = FALSE
    /\ UNCHANGED variables

Recover ==
    /\ replaying /\ ~recovered
    /\ Progress
    /\ recovered' = (phase' = "kmz")
    /\ UNCHANGED <<recoveryInput, recoveryAge, replaying>>

ReplayNext == Explore \/ BeginRecovery \/ Recover
ReplaySpec == ReplayInit /\ [][ReplayNext]_replayVariables

RecoveredCheckpoint ==
    recovered => durable.checkpoint = recoveryInput.journal /\ durable.journal = 0
RecoveryKeepsPublication ==
    replaying => durable.kmz = recoveryInput.kmz
                 /\ durable.publication = recoveryInput.publication
                 /\ durable.viewer = recoveryInput.viewer
\* The original publication checks apply to the unmodified Explore subgraph.
BaseCompletedPublicationConsistent == ~replaying => CompletedPublicationConsistent
BasePublicationRequiresFreshInputs == ~replaying => PublicationRequiresFreshInputs
BaseFreshPublicationPrecedesAcknowledgment == ~replaying => FreshPublicationPrecedesAcknowledgment
BaseGatedPartialInvalidatesPublication == ~replaying => GatedPartialInvalidatesPublication
BaseUngatedPartialCannotAcknowledgeFreshInputs == ~replaying => UngatedPartialCannotAcknowledgeFreshInputs
BaseRankIsNatural == ~replaying => RankIsNatural
BaseProgressAvailable == ~replaying => ProgressAvailable
BaseRankDecreases == [][(~replaying /\ ~replaying') => Rank' < Rank]_replayVariables
=============================================================================
