--------------------------- MODULE ProductRetention ---------------------------
EXTENDS Naturals, FiniteSets, Sequences

\* Each token represents a complete immutable (context, namespace, key, checksum,
\* value) row. Two products belong to each of three dependency contexts.
Rows == {1, 2, 3, 4, 5, 6}
Context(row) == 1 + ((row - 1) \div 2)

VARIABLES retained, durable, pending, phase, retired, readerPhase, reader,
          footprint, trace
variables == <<retained, durable, pending, phase, retired, readerPhase, reader,
               footprint, trace>>
Selected == {row \in Rows : Context(row) \in retained}

Init == /\ retained \in {contexts \in SUBSET (1..3) : 1 \in contexts}
        /\ durable = Rows /\ pending = Rows /\ phase = 0 /\ retired = FALSE
        /\ readerPhase = 0 /\ reader = {} /\ footprint = Cardinality(Rows)
        /\ trace = <<>>

\* Completed application products have committed before this optional cleanup.
Delete == /\ phase = 0 /\ pending' = Selected /\ phase' = 1
          /\ UNCHANGED <<retained, durable, retired, readerPhase, reader, footprint>>
Commit == /\ phase = 1 /\ readerPhase # 1
          /\ durable' = pending /\ retired' = TRUE /\ phase' = 2
          /\ UNCHANGED <<retained, pending, readerPhase, reader, footprint>>
\* SQL failure, cancellation, and a reader-blocked commit preserve committed rows.
Rollback == /\ phase = 1 /\ pending' = durable /\ phase' = 3
            /\ UNCHANGED <<retained, durable, retired, readerPhase, reader, footprint>>
DeleteFailure == /\ phase = 0 /\ phase' = 3
                 /\ UNCHANGED <<retained, durable, pending, retired,
                                readerPhase, reader, footprint>>
\* SQLite compaction changes physical allocation but does not change logical rows.
Compact == /\ phase = 2 /\ readerPhase # 1
           /\ footprint' = Cardinality(durable) /\ phase' = 3
           /\ UNCHANGED <<retained, durable, pending, retired, readerPhase, reader>>
DeferCompact == /\ phase = 2 /\ phase' = 3
                /\ UNCHANGED <<retained, durable, pending, retired,
                               readerPhase, reader, footprint>>
OpenReader == /\ phase # 3 /\ readerPhase = 0
              /\ reader' = durable /\ readerPhase' = 1
              /\ UNCHANGED <<retained, durable, pending, phase, retired, footprint>>
CloseReader == /\ phase # 3 /\ readerPhase = 1
               /\ reader' = {} /\ readerPhase' = 2
               /\ UNCHANGED <<retained, durable, pending, phase, retired, footprint>>

Next == \/ Delete /\ trace' = Append(trace, 1)
        \/ Commit /\ trace' = Append(trace, 2)
        \/ Rollback /\ trace' = Append(trace, 3)
        \/ DeleteFailure /\ trace' = Append(trace, 4)
        \/ Compact /\ trace' = Append(trace, 5)
        \/ DeferCompact /\ trace' = Append(trace, 6)
        \/ OpenReader /\ trace' = Append(trace, 7)
        \/ CloseReader /\ trace' = Append(trace, 8)
Spec == Init /\ [][Next]_variables

RetainedProductsSurvive == Selected \subseteq durable
NoInventedProducts == durable \subseteq Rows
RetirementIsComplete == retired => durable = Selected
UncommittedRetirementIsInvisible == ~retired => durable = Rows
ReadersObserveWholeCommittedStates == reader \in {{}, Rows, Selected}
PhysicalStorageCoversLogicalRows == footprint >= Cardinality(durable)
=============================================================================
