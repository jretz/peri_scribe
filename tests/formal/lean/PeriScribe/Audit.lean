import Lean

/- Dependency inspection prevents proof placeholders and new assumptions entering CI. -/
open Lean Elab Command in
elab "audit_peri_scribe" : command => do
  let environment ← getEnv
  let allowed := [``propext, ``Quot.sound, ``Classical.choice]
  let mut checked : Nat := 0
  for (name, information) in environment.constants.toList do
    if (`PeriScribe).isPrefixOf name then
      match information with
      | .axiomInfo _ => throwError "Project axiom is forbidden: {name}"
      | .thmInfo _ =>
        let dependencies ← collectAxioms name
        for dependency in dependencies do
          unless allowed.contains dependency do
            throwError "Theorem {name} depends on forbidden axiom {dependency}"
        checked := checked + 1
      | _ => pure ()
  if checked = 0 then throwError "No PeriScribe theorems were audited"
  logInfo m!"Audited {checked} theorem declarations: only standard Lean axioms."
