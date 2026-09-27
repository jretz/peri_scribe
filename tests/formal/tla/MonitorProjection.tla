--------------------------- MODULE MonitorProjection ---------------------------
EXTENDS Integers, Sequences, FiniteSets

CONSTANT MaximumEvents, Window
Times == 0..3
Clocks == 0..6
Event == [when: Times, successful: BOOLEAN]
VARIABLES events, periods, previousTime, currentTime, diagnostic, phase,
          cachedCoverage, coverage, latestSuccess, reused
variables == <<events, periods, previousTime, currentTime, diagnostic, phase,
               cachedCoverage, coverage, latestSuccess, reused>>

RECURSIVE Insert(_, _)
Insert(period, ordered) ==
    IF ordered = <<>> THEN <<period>>
    ELSE IF period.start <= Head(ordered).start THEN <<period>> \o ordered
    ELSE <<Head(ordered)>> \o Insert(period, Tail(ordered))
RECURSIVE Merge(_, _)
Merge(ordered, result) ==
    IF ordered = <<>> THEN result
    ELSE IF result = <<>> THEN Merge(Tail(ordered), <<Head(ordered)>>)
    ELSE LET last == result[Len(result)] IN
        IF Head(ordered).start <= last.finish THEN
            Merge(Tail(ordered), [result EXCEPT ![Len(result)].finish =
                IF @ >= Head(ordered).finish THEN @ ELSE Head(ordered).finish])
        ELSE Merge(Tail(ordered), Append(result, Head(ordered)))

Covered(at) == \E index \in DOMAIN periods:
                  periods[index].start <= at /\ at <= periods[index].finish
Expected(at) == \E index \in DOMAIN events:
                   events[index].when <= at /\ at <= events[index].when + Window
Health(at) == IF diagnostic > 0 THEN 2 ELSE IF Covered(at) THEN 0 ELSE 3
Deadlines == {periods[index].start: index \in DOMAIN periods}
             \cup {periods[index].finish + 1: index \in DOMAIN periods}
NoBoundary == ~\E deadline \in Deadlines:
                previousTime < deadline /\ deadline <= currentTime
SuccessfulIndices == {index \in DOMAIN events:
    events[index].successful /\ events[index].when <= currentTime}
Successful == {events[index].when: index \in SuccessfulIndices}
Init == /\ events = <<>> /\ periods = <<>> /\ previousTime \in Clocks
        /\ currentTime \in Clocks /\ diagnostic \in 0..2 /\ phase = "append"
        /\ cachedCoverage = 3 /\ coverage = 3 /\ latestSuccess = -1
        /\ reused = FALSE
AppendEvent(event) ==
    /\ phase = "append" /\ Len(events) < MaximumEvents
    /\ events' = Append(events, event)
    /\ periods' = Merge(Insert([start |-> event.when,
                                finish |-> event.when + Window], periods), <<>>)
    /\ UNCHANGED <<previousTime, currentTime, diagnostic, phase, cachedCoverage,
                   coverage, latestSuccess, reused>>
Observe ==
    /\ phase = "append" /\ phase' = "refresh"
    /\ cachedCoverage' = Health(previousTime)
    /\ UNCHANGED <<events, periods, previousTime, currentTime, diagnostic,
                   coverage, latestSuccess, reused>>
Refresh ==
    /\ phase = "refresh" /\ phase' = "done"
    /\ reused' = (currentTime >= previousTime /\ NoBoundary)
    /\ coverage' = IF reused' THEN cachedCoverage ELSE Health(currentTime)
    /\ latestSuccess' = IF Successful = {} THEN -1
                         ELSE CHOOSE newest \in Successful:
                             \A other \in Successful: newest >= other
    /\ UNCHANGED <<events, periods, previousTime, currentTime, diagnostic,
                   cachedCoverage>>
Next == (\E event \in Event: AppendEvent(event)) \/ Observe \/ Refresh
Spec == Init /\ [][Next]_variables
CompactionPreservesCoverage == \A at \in Clocks: Covered(at) <=> Expected(at)
IntervalsDisjoint == \A index \in 1..(Len(periods) - 1):
                        periods[index].finish < periods[index + 1].start
CacheAgreesWithFresh == phase = "done" => coverage = Health(currentTime)
DiagnosticsPreventHealthy == phase = "done" /\ diagnostic > 0 => coverage = 2
FailuresCannotAcknowledge == phase = "done" /\ latestSuccess # -1 =>
    latestSuccess \in Successful /\ \A other \in Successful: other <= latestSuccess
=============================================================================
