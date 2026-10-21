------------------------- MODULE NormalizedCache ---------------------------
EXTENDS Naturals, Sequences, FiniteSets

Payloads == {1, 2}
Keys == {1, 2}
Sequences == {<<>>, <<1>>, <<2>>, <<1, 1>>, <<1, 2>>, <<2, 1>>}
VARIABLES original, target, durable, pending, phase, position, answer
variables == <<original, target, durable, pending, phase, position, answer>>

Decode(state) == [i \in 1..Len(state.rows) |-> state.dictionary[state.rows[i]]]
References(state) == {state.rows[i] : i \in 1..Len(state.rows)}
Complete(sequence) == [dictionary |->
                        [key \in {sequence[i] : i \in 1..Len(sequence)} |-> key],
                       rows |-> sequence, receipt |-> sequence]
Consistent(state) == /\ References(state) \subseteq DOMAIN state.dictionary
                     /\ Decode(state) = state.receipt

Init ==
    /\ original \in Sequences /\ target \in Sequences
    /\ durable = Complete(original) /\ pending = durable
    /\ phase = "building" /\ position = 0 /\ answer = <<>>

Begin ==
    /\ phase = "building" /\ position = 0
    /\ pending' = [pending EXCEPT !.rows = <<>>, !.receipt = target]
    /\ position' = 1
    /\ UNCHANGED <<original, target, durable, phase, answer>>

WriteRow ==
    /\ phase = "building" /\ position \in 1..Len(target)
    /\ LET payload == target[position]
           existing == {key \in DOMAIN pending.dictionary :
                         pending.dictionary[key] = payload}
           key == IF existing # {} THEN CHOOSE key \in existing : TRUE
                  ELSE CHOOSE key \in Keys \ DOMAIN pending.dictionary : TRUE
       IN /\ pending' = [pending EXCEPT
              !.dictionary = IF existing # {} THEN @
                ELSE [candidate \in DOMAIN @ \cup {key} |->
                       IF candidate = key THEN payload ELSE @[candidate]],
              !.rows = Append(@, key)]
    /\ position' = position + 1
    /\ UNCHANGED <<original, target, durable, phase, answer>>

Collect ==
    /\ phase = "building" /\ position = Len(target) + 1
    /\ pending' = [pending EXCEPT !.dictionary =
          [key \in References(pending) |-> @[key]]]
    /\ phase' = "ready"
    /\ UNCHANGED <<original, target, durable, position, answer>>

Publish ==
    /\ phase = "ready" /\ durable' = pending /\ phase' = "published"
    /\ UNCHANGED <<original, target, pending, position, answer>>

Abort ==
    /\ phase \in {"building", "ready"}
    /\ pending' = durable /\ phase' = "aborted"
    /\ UNCHANGED <<original, target, durable, position, answer>>

Restart ==
    /\ phase = "aborted" /\ pending' = durable
    /\ position' = 0 /\ phase' = "building"
    /\ UNCHANGED <<original, target, durable, answer>>

Read ==
    /\ answer' = <<durable.receipt, Decode(durable)>>
    /\ UNCHANGED <<original, target, durable, pending, phase, position>>

Next == Begin \/ WriteRow \/ Collect \/ Publish \/ Abort \/ Restart \/ Read
Spec == Init /\ [][Next]_variables
DurableReferencesResolve == References(durable) \subseteq DOMAIN durable.dictionary
DurableMatchesReceipt == Consistent(durable)
PublishedMatchesTarget == phase = "published" => Decode(durable) = target
AuthenticatedAnswer == answer # <<>> => answer[1] = answer[2]
=============================================================================
