-------------------------- MODULE MonitorSession --------------------------
EXTENDS Integers, FiniteSets

CONSTANTS Requests, Urgent, Subscribers
VARIABLES queued, active, done, stopped, closed, version, connected, pending,
          received, urgent
variables == <<queued, active, done, stopped, closed, version, connected,
               pending, received, urgent>>

Init ==
    /\ queued = {} /\ active = 0 /\ done = {} /\ urgent = Urgent
    /\ stopped = FALSE /\ closed = FALSE /\ version = 0
    /\ connected = {}
    /\ pending = [subscriber \in Subscribers |-> -1]
    /\ received = [subscriber \in Subscribers |-> -1]

Submit(request) ==
    /\ ~stopped /\ request \notin queued \cup done \cup {active}
    /\ queued' = queued \cup {request}
    /\ UNCHANGED <<active, done, stopped, closed, version, connected, pending,
                    received, urgent>>

Admit(request) ==
    /\ ~stopped /\ active = 0 /\ request \in queued
    /\ (queued \cap urgent # {} => request \in urgent)
    /\ queued' = queued \ {request} /\ active' = request
    /\ UNCHANGED <<done, stopped, closed, version, connected, pending, received,
                    urgent>>

Promote(request) ==
    /\ request \in queued /\ request \notin urgent
    /\ urgent' = urgent \cup {request}
    /\ UNCHANGED <<queued, active, done, stopped, closed, version, connected,
                    pending, received>>

Cancel(request) ==
    /\ request \in queued
    /\ queued' = queued \ {request} /\ done' = done \cup {request}
    /\ UNCHANGED <<active, stopped, closed, version, connected, pending, received,
                    urgent>>

Complete ==
    /\ active # 0
    /\ version' = IF stopped THEN version ELSE version + 1
    /\ pending' = IF stopped THEN pending ELSE
        [subscriber \in Subscribers |->
            IF subscriber \in connected THEN version' ELSE pending[subscriber]]
    /\ done' = done \cup {active} /\ active' = 0
    /\ UNCHANGED <<queued, stopped, closed, connected, received, urgent>>

Fail ==
    /\ active # 0 /\ done' = done \cup {active} /\ active' = 0
    /\ UNCHANGED <<queued, stopped, closed, version, connected, pending, received,
                    urgent>>

Subscribe(subscriber) ==
    /\ ~stopped /\ subscriber \notin connected
    /\ connected' = connected \cup {subscriber}
    /\ pending' = [pending EXCEPT ![subscriber] = version]
    /\ UNCHANGED <<queued, active, done, stopped, closed, version, received, urgent>>

Receive(subscriber) ==
    /\ subscriber \in connected /\ pending[subscriber] >= 0
    /\ received' = [received EXCEPT ![subscriber] = pending[subscriber]]
    /\ pending' = [pending EXCEPT ![subscriber] = -1]
    /\ UNCHANGED <<queued, active, done, stopped, closed, version, connected, urgent>>

Disconnect(subscriber) ==
    /\ subscriber \in connected
    /\ connected' = connected \ {subscriber}
    /\ pending' = [pending EXCEPT ![subscriber] = -1]
    /\ UNCHANGED <<queued, active, done, stopped, closed, version, received, urgent>>

Stop ==
    /\ ~stopped /\ stopped' = TRUE
    /\ done' = done \cup queued /\ queued' = {}
    /\ UNCHANGED <<active, closed, version, connected, pending, received, urgent>>

Close ==
    /\ stopped /\ active = 0 /\ ~closed /\ closed' = TRUE
    /\ pending' = [subscriber \in Subscribers |-> -1]
    /\ connected' = {}
    /\ UNCHANGED <<queued, active, done, stopped, version, received, urgent>>

Next == (\E request \in Requests:
        Submit(request) \/ Admit(request) \/ Cancel(request) \/ Promote(request))
    \/ Complete \/ Fail \/ Stop \/ Close
    \/ (\E subscriber \in Subscribers:
        Subscribe(subscriber) \/ Receive(subscriber) \/ Disconnect(subscriber))
Spec == Init /\ [][Next]_variables

TypeOK ==
    /\ queued \subseteq Requests /\ active \in Requests \cup {0}
    /\ done \subseteq Requests /\ urgent \subseteq Requests
    /\ stopped \in BOOLEAN /\ closed \in BOOLEAN
    /\ version \in 0..Cardinality(Requests) /\ connected \subseteq Subscribers
    /\ pending \in [Subscribers -> (-1)..Cardinality(Requests)]
    /\ received \in [Subscribers -> (-1)..Cardinality(Requests)]
ExclusiveOwner == active \notin queued \cup done
RetainedResources == closed => stopped /\ active = 0 /\ queued = {}
CurrentSubscription == \A subscriber \in connected:
    pending[subscriber] = -1 \/ pending[subscriber] = version
MonotonicDelivery == [][\A subscriber \in Subscribers:
    received'[subscriber] >= received[subscriber]]_variables
NoLatePublication == [][stopped => version' = version]_variables
=============================================================================
