---------------------------- MODULE GroupingForest ----------------------------
EXTENDS Naturals, FiniteSets

CONSTANT Nodes
NoNode == 0
Pairs == {<<left, right>> \in Nodes \X Nodes : left < right}
Edge(left, right) == IF left < right THEN <<left, right>> ELSE <<right, left>>
Adjacent(edges, left, right) == Edge(left, right) \in edges

RECURSIVE Reach(_, _, _)
Reach(edges, reached, steps) ==
    IF steps = 0 THEN reached
    ELSE Reach(edges,
               reached \cup {right \in Nodes : \E left \in reached:
                                    Adjacent(edges, left, right)}, steps - 1)
Connected(edges, left, right) == right \in Reach(edges, {left}, Cardinality(Nodes))

VARIABLES graph, active, pending, current, forest
variables == <<graph, active, pending, current, forest>>

Init == /\ graph \in SUBSET Pairs
        /\ active = Nodes /\ pending = {} /\ current = NoNode /\ forest = {}

Seed == /\ current = NoNode /\ pending = {} /\ active # {}
        /\ \E node \in active:
             /\ active' = active \ {node} /\ pending' = {node}
        /\ UNCHANGED <<graph, current, forest>>
Admit == /\ current = NoNode /\ pending # {}
         /\ \E node \in pending:
              /\ pending' = pending \ {node} /\ current' = node
         /\ UNCHANGED <<graph, active, forest>>
Discover == /\ current # NoNode
            /\ \E node \in active:
                 /\ Adjacent(graph, current, node)
                 /\ active' = active \ {node}
                 /\ pending' = pending \cup {node}
                 /\ forest' = forest \cup {Edge(current, node)}
            /\ UNCHANGED <<graph, current>>
Finish == /\ current # NoNode
          /\ \A node \in active: ~Adjacent(graph, current, node)
          /\ current' = NoNode
          /\ UNCHANGED <<graph, active, pending, forest>>
Next == Seed \/ Admit \/ Discover \/ Finish
Spec == Init /\ [][Next]_variables

TypeOK == /\ graph \subseteq Pairs /\ forest \subseteq Pairs
          /\ active \subseteq Nodes /\ pending \subseteq Nodes
          /\ current \in Nodes \cup {NoNode}
OnlyRealEdges == forest \subseteq graph
NoDiscoveryTwice == /\ active \cap pending = {}
                    /\ current \notin active
                    /\ current \notin pending
Done == active = {} /\ pending = {} /\ current = NoNode
SameFinalComponents == Done =>
    \A left, right \in Nodes:
        Connected(graph, left, right) = Connected(forest, left, right)
Completed == Nodes \ (active \cup pending \cup {current})
ExhaustedCut == \A left \in Completed, right \in active:
                   ~Adjacent(graph, left, right)
ForestBound == Cardinality(forest) < Cardinality(Nodes)
=============================================================================
