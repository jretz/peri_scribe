--------------------------- MODULE PublicationGate ---------------------------
EXTENDS Integers

\* Shape interpretation is a boundary: comparison categories come from domain tests.
Inputs == [checkpointValid: BOOLEAN, evacuationsChanged: BOOLEAN, citiesChanged: BOOLEAN,
           historyChanged: BOOLEAN, newSnapshots: BOOLEAN,
           mappingUncertain: BOOLEAN, olderMapping: BOOLEAN,
           areaChange: -2..2, timerDue: BOOLEAN,
           fullFetch: BOOLEAN, forced: BOOLEAN, pending: BOOLEAN]
Absolute(number) == IF number < 0 THEN -number ELSE number

GateReason(input) ==
    CASE ~input.checkpointValid -> "no publication"
      [] input.evacuationsChanged -> "evacuations"
      [] input.citiesChanged -> "cities"
      [] input.historyChanged -> "source history"
      [] ~input.newSnapshots -> "no changes"
      [] input.mappingUncertain -> "uncertain mapping"
      [] ~input.olderMapping /\ Absolute(input.areaChange) >= 2 -> "area"
      [] input.timerDue -> "timer"
      [] OTHER -> "below threshold"

VARIABLES input, reason, decision, run
variables == <<input, reason, decision, run>>
Init ==
    /\ input \in Inputs
    /\ reason = GateReason(input)
    /\ decision = (reason \notin {"no changes", "below threshold"})
    /\ run = (decision \/ input.fullFetch \/ input.forced \/ input.pending)
Next == UNCHANGED variables
Spec == Init /\ [][Next]_variables

TypeOK ==
    /\ input \in Inputs
    /\ reason \in {"no publication", "evacuations", "cities", "source history",
                   "no changes", "uncertain mapping", "area", "timer",
                   "below threshold"}
    /\ decision \in BOOLEAN
    /\ run \in BOOLEAN
RebuildOverridesGate == input.fullFetch \/ input.forced \/ input.pending => run
SkipRequiresEvidence ==
    ~run => input.checkpointValid /\ ~input.evacuationsChanged
            /\ ~input.citiesChanged /\ ~input.historyChanged /\ ~input.pending
CitiesRequirePublication == input.citiesChanged => run
TimerNeedsUnpublishedInputs ==
    reason = "timer" => input.newSnapshots /\ input.timerDue
NoChangesIgnoreTimer ==
    input.checkpointValid /\ ~input.evacuationsChanged /\ ~input.historyChanged
    /\ ~input.citiesChanged /\ ~input.newSnapshots => ~decision
AreaIncludesShrinkage ==
    input.checkpointValid /\ ~input.evacuationsChanged /\ ~input.historyChanged
    /\ ~input.citiesChanged /\ input.newSnapshots
    /\ ~input.mappingUncertain /\ ~input.olderMapping
    /\ Absolute(input.areaChange) = 2 => reason = "area"
=============================================================================
