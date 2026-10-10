import Std

namespace PeriScribe.Pipeline

/-- Derived stages retain the prerequisite order used by the recovery file. -/
inductive Stage where
  | geography | score | kmz | reports
  deriving DecidableEq, Repr

def stages : List Stage := [.geography, .score, .kmz, .reports]

/-- Persistence is abstracted away; this is the validated recovery payload. -/
structure Pending where
  remaining : List Stage
  unconditional : Bool
  deriving DecidableEq, Repr

/-- Only the first outstanding prerequisite can acknowledge successful work. -/
def complete (state : Pending) (stage : Stage) : Pending :=
  match state.remaining with
  | [] => state
  | first :: rest =>
    if first = stage then
      ⟨rest, if rest.isEmpty then false else state.unconditional⟩
    else state

/-- Invalidating new work preserves all previous requirements in canonical order. -/
def require (state : Pending) (requested : List Stage) (force : Bool) : Pending :=
  ⟨stages.filter (fun stage => stage ∈ state.remaining ∨ stage ∈ requested),
    state.unconditional || force⟩

theorem later_success_preserves_prerequisite (first stage : Stage)
    (rest : List Stage) (force : Bool) (different : first ≠ stage) :
    complete ⟨first :: rest, force⟩ stage = ⟨first :: rest, force⟩ := by
  simp [complete, different]

theorem prerequisite_success_removes_only_head (first : Stage)
    (rest : List Stage) (force : Bool) :
    (complete ⟨first :: rest, force⟩ first).remaining = rest := by
  simp [complete]

theorem force_survives_unfinished_work (first next : Stage)
    (rest : List Stage) :
    (complete ⟨first :: next :: rest, true⟩ first).unconditional = true := by
  simp [complete]

theorem last_success_clears_force (last : Stage) (force : Bool) :
    complete ⟨[last], force⟩ last = ⟨[], false⟩ := by
  simp [complete]

theorem completing_empty_is_noop (stage : Stage) (force : Bool) :
    complete ⟨[], force⟩ stage = ⟨[], force⟩ := by
  rfl

theorem all_stages_enumerated (stage : Stage) : stage ∈ stages := by
  cases stage <;> simp [stages]

theorem require_membership (state : Pending) (requested : List Stage)
    (force : Bool) (stage : Stage) :
    stage ∈ (require state requested force).remaining ↔
      stage ∈ state.remaining ∨ stage ∈ requested := by
  simp [require, all_stages_enumerated]

theorem require_preserves_force (state : Pending) (requested : List Stage)
    (force : Bool) (alreadyForced : state.unconditional = true) :
    (require state requested force).unconditional = true := by
  simp [require, alreadyForced]

/-- Decision order matches publication.decide after mapping comparison is complete. -/
inductive Reason where
  | noPublication | evacuations | cities | sourceHistory | noChanges
  | area | timer | belowThreshold
  deriving DecidableEq, Repr

structure Decision where
  proceed : Bool
  reason : Reason
  deriving DecidableEq, Repr

def gate
    (valid evacuationsChanged citiesChanged historyChanged pending
      mappingProceed timerDue : Bool)
    : Decision :=
  if !valid then ⟨true, .noPublication⟩
  else if evacuationsChanged then ⟨true, .evacuations⟩
  else if citiesChanged then ⟨true, .cities⟩
  else if historyChanged then ⟨true, .sourceHistory⟩
  else if !pending then ⟨false, .noChanges⟩
  else if mappingProceed then ⟨true, .area⟩
  else if timerDue then ⟨true, .timer⟩
  else ⟨false, .belowThreshold⟩

theorem invalid_checkpoint_never_skips
    (evacuations cities history pending mapping timer : Bool) :
    (gate false evacuations cities history pending mapping timer).proceed = true := by
  simp [gate]

theorem changed_cities_require_publication
    (valid evacuations history pending mapping timer : Bool) :
    (gate valid evacuations true history pending mapping timer).proceed = true := by
  cases valid <;> cases evacuations <;> simp [gate]

theorem timer_needs_pending_data (mapping timer : Bool) :
    gate true false false false false mapping timer = ⟨false, .noChanges⟩ := by
  simp [gate]

theorem pending_timer_eventually_proceeds (mapping : Bool) :
    (gate true false false false true mapping true).proceed = true := by
  cases mapping <;> rfl

theorem skip_requires_trustworthy_unchanged_baseline
    (valid evacuations cities history pending mapping timer : Bool)
    (skipped :
      (gate valid evacuations cities history pending mapping timer).proceed = false) :
    valid = true ∧ evacuations = false ∧ cities = false ∧ history = false := by
  cases valid <;> cases evacuations <;> cases cities <;> cases history <;>
    simp_all [gate]

end PeriScribe.Pipeline
