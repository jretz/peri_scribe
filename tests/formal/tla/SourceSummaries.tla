-------------------------- MODULE SourceSummaries --------------------------
EXTENDS Naturals, Sequences, FiniteSets

Paths == {1, 2}
Revisions == {1, 2}
Modes == {"absent", "damaged", "old-context", "complete"}
Summary(path, revision) == <<path, revision, revision, 1>>
VARIABLES current, previous, modes, products, position, selected, hydrated
variables == <<current, previous, modes, products, position, selected, hydrated>>

Init ==
    /\ current \in [Paths -> Revisions]
    /\ previous \in [Paths -> Revisions]
    /\ modes \in [Paths -> Modes]
    /\ products = [path \in Paths |-> Summary(path, previous[path])]
    /\ position = 1 /\ selected = <<>> /\ hydrated = {}

Hit(path) == modes[path] = "complete" /\ previous[path] = current[path]

Read ==
    /\ position \in Paths
    /\ selected' = Append(selected,
          IF Hit(position) THEN products[position]
          ELSE Summary(position, current[position]))
    /\ hydrated' = IF Hit(position) THEN hydrated ELSE hydrated \cup {position}
    /\ position' = position + 1
    /\ UNCHANGED <<current, previous, modes, products>>

Next == Read
Spec == Init /\ [][Next]_variables
ExactSelected == selected = [path \in 1..(position - 1) |->
                               Summary(path, current[path])]
SelectiveHydration == hydrated = {path \in 1..(position - 1) : ~Hit(path)}
CompleteOrder == position = 3 =>
                  selected = <<Summary(1, current[1]), Summary(2, current[2])>>
=============================================================================
