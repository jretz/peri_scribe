---------------------------- MODULE VerificationAdmission ----------------------------
EXTENDS Naturals, FiniteSets

VARIABLES exited, proof, qa, formal, ordinaryValidated, regularPassed,
          formalPassed, aborted, success, admitted
vars == <<exited, proof, qa, formal, ordinaryValidated, regularPassed,
          formalPassed, aborted, success, admitted>>

Init == /\ exited = 0
        /\ proof = "models"
        /\ qa = "waiting"
        /\ formal = "waiting"
        /\ ordinaryValidated = FALSE
        /\ regularPassed = FALSE
        /\ formalPassed = FALSE
        /\ aborted = FALSE
        /\ success = FALSE
        /\ admitted = 0

OrdinaryExit ==
    /\ ~aborted /\ ~success /\ exited < 4
    /\ exited' = exited + 1
    /\ UNCHANGED <<proof, qa, formal, ordinaryValidated, regularPassed,
                   formalPassed, aborted, success, admitted>>

ProofStep ==
    /\ ~aborted /\ ~success /\ proof \in {"models", "lean", "pristine"}
    /\ proof' = CASE proof = "models" -> "lean"
                    [] proof = "lean" -> "pristine"
                    [] OTHER -> "done"
    /\ UNCHANGED <<exited, qa, formal, ordinaryValidated, regularPassed,
                   formalPassed, aborted, success, admitted>>

OrdinaryValidation ==
    /\ ~aborted /\ ~success /\ exited = 4 /\ ~ordinaryValidated
    /\ ordinaryValidated' = TRUE
    /\ UNCHANGED <<exited, proof, qa, formal, regularPassed,
                   formalPassed, aborted, success, admitted>>

QAStart ==
    /\ ~aborted /\ ~success /\ ordinaryValidated /\ qa = "waiting"
    /\ qa' = "running"
    /\ UNCHANGED <<exited, proof, formal, ordinaryValidated, regularPassed,
                   formalPassed, aborted, success, admitted>>

RegularExit ==
    /\ ~aborted /\ ~success /\ qa = "running"
    /\ qa' = "closed" /\ regularPassed' = TRUE
    /\ UNCHANGED <<exited, proof, formal, ordinaryValidated,
                   formalPassed, aborted, success, admitted>>

FormalStart ==
    /\ ~aborted /\ ~success /\ formal = "waiting"
    /\ proof = "done" /\ regularPassed /\ qa = "closed"
    /\ formal' = "running" /\ admitted' = 5
    /\ UNCHANGED <<exited, proof, qa, ordinaryValidated, regularPassed,
                   formalPassed, aborted, success>>

FormalExit ==
    /\ ~aborted /\ ~success /\ formal = "running"
    /\ formal' = "closed" /\ formalPassed' = TRUE
    /\ UNCHANGED <<exited, proof, qa, ordinaryValidated, regularPassed,
                   aborted, success, admitted>>

Finish ==
    /\ ~aborted /\ ~success /\ formalPassed /\ regularPassed
    /\ ordinaryValidated /\ proof = "done" /\ formal = "closed"
    /\ success' = TRUE
    /\ UNCHANGED <<exited, proof, qa, formal, ordinaryValidated, regularPassed,
                   formalPassed, aborted, admitted>>

Abort ==
    /\ ~aborted /\ ~success /\ aborted' = TRUE
    /\ UNCHANGED <<exited, proof, qa, formal, ordinaryValidated, regularPassed,
                   formalPassed, success, admitted>>

Cleanup ==
    /\ aborted
    /\ exited' = 4 /\ proof' = "stopped"
    /\ qa' = "closed" /\ formal' = "closed"
    /\ UNCHANGED <<ordinaryValidated, regularPassed, formalPassed,
                   aborted, success, admitted>>

Terminal ==
    /\ success \/ (aborted /\ exited = 4 /\ proof = "stopped"
                    /\ qa = "closed" /\ formal = "closed")
    /\ UNCHANGED vars

Next == OrdinaryExit \/ ProofStep
        \/ OrdinaryValidation \/ QAStart \/ RegularExit
        \/ FormalStart \/ FormalExit \/ Finish
        \/ Abort \/ Cleanup \/ Terminal
Spec == Init /\ [][Next]_vars

FormalSlots == IF formal = "running" THEN 5 ELSE 0
ProofSlots == IF proof \in {"models", "lean", "pristine"} THEN 1 ELSE 0
QASlots == IF qa = "running" THEN 3 ELSE 0
TypeOK == /\ exited \in 0..4
          /\ proof \in {"models", "lean", "pristine", "done", "stopped"}
          /\ qa \in {"waiting", "running", "closed"}
          /\ formal \in {"waiting", "running", "closed"}
          /\ ordinaryValidated \in BOOLEAN /\ regularPassed \in BOOLEAN
          /\ formalPassed \in BOOLEAN /\ aborted \in BOOLEAN /\ success \in BOOLEAN
          /\ admitted \in {0, 5}
NominalCapacity == 4 - exited + ProofSlots + QASlots + FormalSlots <= 5
QualifiedFormal == formal = "running" => proof = "done" /\ regularPassed /\ qa = "closed"
QualifiedQA == qa = "running" => ordinaryValidated /\ exited = 4
NoFalseSuccess == success => ~aborted /\ ordinaryValidated /\ regularPassed
                             /\ formalPassed /\ proof = "done" /\ formal = "closed"
NoAdmissionAfterAbort == [][aborted => admitted' = admitted]_vars
=============================================================================
