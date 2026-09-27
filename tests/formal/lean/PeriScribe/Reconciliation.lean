import Std

namespace PeriScribe.Reconciliation

/-- A single measurement keeps the identity of its supporting source row. -/
structure Measurement where
  value : Nat
  provenance : Nat
  confirmedAt : Option Nat
  deriving DecidableEq, Repr

/-- Arguments are ordered by feed priority; equal values preserve newer confirmation. -/
def winner (previous current : Measurement) : Measurement :=
  if previous.value = current.value then
    match previous.confirmedAt, current.confirmedAt with
    | some _, none => previous
    | some previousTime, some currentTime =>
      if currentTime < previousTime then previous else current
    | _, _ => current
  else current

theorem winner_keeps_whole_evidence (previous current : Measurement) :
    winner previous current = previous ∨ winner previous current = current := by
  unfold winner
  split
  · cases previous.confirmedAt with
    | none => simp
    | some previousTime =>
      cases current.confirmedAt with
      | none => simp
      | some currentTime =>
        by_cases newer : currentTime < previousTime <;> simp [newer]
  · exact Or.inr rfl

theorem conflicting_values_follow_feed_priority (previous current : Measurement)
    (different : previous.value ≠ current.value) :
    winner previous current = current := by
  simp [winner, different]

theorem identical_reports_are_idempotent (measurement : Measurement) :
    winner measurement measurement = measurement := by
  simp [winner]
  cases measurement.confirmedAt <;> simp

theorem confirmation_survives_unconfirmed_duplicate
    (previous current : Measurement) (time : Nat)
    (same : previous.value = current.value)
    (confirmed : previous.confirmedAt = some time)
    (unconfirmed : current.confirmedAt = none) :
    winner previous current = previous := by
  simp [winner, same, confirmed, unconfirmed]

/-- This local rule models a supplied field after simultaneous-feed reconciliation. -/
def preserveConfirmed (previous current : Nat) (confirmed stale isArea : Bool) : Nat :=
  if !confirmed && stale && !(isArea && decide (previous < current)) then previous
  else current

theorem stale_edit_preserves_nonarea_measurement (previous current : Nat) :
    preserveConfirmed previous current false true false = previous := by
  simp [preserveConfirmed]

theorem newly_confirmed_corrections_win (previous current : Nat) (stale area : Bool) :
    preserveConfirmed previous current true stale area = current := by
  simp [preserveConfirmed]

theorem unconfirmed_area_growth_remains_eligible (previous current : Nat)
    (growth : previous < current) :
    preserveConfirmed previous current false true true = current := by
  simp [preserveConfirmed, growth]

theorem stale_unconfirmed_area_cannot_decrease (previous current : Nat) :
    previous ≤ preserveConfirmed previous current false true true := by
  unfold preserveConfirmed
  by_cases growth : previous < current
  · simp [growth]
    omega
  · simp [growth]

end PeriScribe.Reconciliation
