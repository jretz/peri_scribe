------------------------ MODULE MonitorBackwardContext ------------------------
EXTENDS Naturals, Sequences, FiniteSets

Record == {item \in [run: 0..1, important: BOOLEAN, start: BOOLEAN]:
               item.start => item.important}
Histories == UNION {[1..length -> Record]: length \in 0..4}
StartFirst(history) == \A index \in DOMAIN history:
    history[index].start => \A earlier \in 1..(index - 1):
        history[earlier].run # history[index].run

VARIABLES records, runs, pending, position, selected, result, ready
variables == <<records, runs, pending, position, selected, result, ready>>
Eligible(index) == records[index].run \in runs /\ records[index].important
Expected == SelectSeq([index \in DOMAIN records |-> index], Eligible)

Init == /\ records \in Histories /\ StartFirst(records)
        /\ runs \in SUBSET (0..1)
        /\ pending = runs /\ position = Len(records)
        /\ selected = <<>> /\ result = <<>> /\ ready = FALSE

Scan == /\ ~ready /\ pending # {} /\ position > 0
        /\ LET item == records[position]
           IN /\ selected' = IF item.run \in pending /\ item.important
                                THEN <<position>> \o selected ELSE selected
              /\ pending' = IF item.start THEN pending \ {item.run} ELSE pending
        /\ position' = position - 1
        /\ UNCHANGED <<records, runs, result, ready>>

Finish == /\ ~ready /\ (pending = {} \/ position = 0)
          /\ result' = IF pending = {} THEN selected ELSE Expected
          /\ ready' = TRUE
          /\ UNCHANGED <<records, runs, pending, position, selected>>

Next == Scan \/ Finish
Spec == Init /\ [][Next]_variables
FairSpec == Spec /\ WF_variables(Next)
ExactContext == ready => result = Expected
NoDuplicates == Cardinality({selected[index]: index \in DOMAIN selected}) = Len(selected)
PreservesOrder == \A first, second \in DOMAIN selected:
    first < second => selected[first] < selected[second]
ContextComplete == <>ready
=============================================================================
