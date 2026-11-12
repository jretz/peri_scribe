import Std

namespace PeriScribe.RankedLiveness

/-- A natural-number rank and weakly fair progress imply arrival at a final state.
    Each nonstuttering step decreases the rank. If no final state is reached,
    progress remains enabled and fairness forces another decrease from every suffix. -/
theorem eventuallyFinal {State : Type}
    (trace : Nat → State) (rank : State → Nat) (final enabled : State → Prop)
    (step : ∀ index, trace (index + 1) = trace index ∨
      rank (trace (index + 1)) < rank (trace index))
    (nonfinalEnables : ∀ state, ¬ final state → enabled state)
    (weakFair : ∀ start, (∀ index, start ≤ index → enabled (trace index)) →
      ∃ index, start ≤ index ∧ trace (index + 1) ≠ trace index) :
    ∃ index, final (trace index) := by
  classical
  refine Classical.byContradiction ?_
  intro absent
  have neverFinal (index : Nat) : ¬ final (trace index) :=
    fun visited => absent ⟨index, visited⟩
  have between (start offset : Nat) : rank (trace (start + offset)) ≤ rank (trace start) := by
    induction offset with
    | zero => simp
    | succ offset previous =>
      rcases step (start + offset) with equal | smaller
      · rw [Nat.add_succ, equal]
        exact previous
      · exact Nat.le_trans (Nat.le_of_lt smaller) previous
  have smallerLater (start : Nat) : ∃ index, rank (trace index) < rank (trace start) := by
    obtain ⟨index, afterStart, moved⟩ := weakFair start
      (fun later _ => nonfinalEnables (trace later) (neverFinal later))
    have lower := (step index).resolve_left moved
    have bounded := between start (index - start)
    rw [Nat.add_sub_of_le afterStart] at bounded
    exact ⟨index + 1, Nat.lt_of_lt_of_le lower bounded⟩
  have impossible : ∀ value, ∀ index, rank (trace index) = value → False := by
    intro value
    induction value using Nat.strongRecOn with
    | ind value hypothesis =>
      intro index equal
      obtain ⟨later, smaller⟩ := smallerLater index
      rw [equal] at smaller
      exact hypothesis _ smaller later rfl
  exact impossible _ 0 rfl

/-- An unmoving suffix keeps one individually fair action enabled from its first state. -/
theorem familyFairness {State Action : Type}
    (trace : Nat → State) (enabled : Action → State → Prop)
    (eachFair : ∀ action start, (∀ index, start ≤ index → enabled action (trace index)) →
      ∃ index, start ≤ index ∧ trace (index + 1) ≠ trace index)
    (start : Nat) (available : ∀ index, start ≤ index → ∃ action, enabled action (trace index)) :
    ∃ index, start ≤ index ∧ trace (index + 1) ≠ trace index := by
  classical
  refine Classical.byContradiction ?_
  intro noMove
  have fixed (offset : Nat) : trace (start + offset) = trace start := by
    induction offset with
    | zero => simp
    | succ offset previous =>
      have same : trace (start + offset + 1) = trace (start + offset) := by
        refine Classical.byContradiction ?_
        intro changed
        exact noMove ⟨start + offset, Nat.le_add_right start offset, changed⟩
      rw [Nat.add_succ, same, previous]
  obtain ⟨action, initiallyEnabled⟩ := available start (Nat.le_refl start)
  apply noMove (eachFair action start ?_)
  intro index afterStart
  rw [← Nat.add_sub_of_le afterStart, fixed]
  exact initiallyEnabled

/-- Individually fair actions suffice when at least one is enabled until completion. -/
theorem eventuallyFinalOfFamily {State Action : Type}
    (trace : Nat → State) (rank : State → Nat) (final : State → Prop)
    (enabled : Action → State → Prop)
    (step : ∀ index, trace (index + 1) = trace index ∨
      rank (trace (index + 1)) < rank (trace index))
    (nonfinalEnables : ∀ state, ¬ final state → ∃ action, enabled action state)
    (eachFair : ∀ action start, (∀ index, start ≤ index → enabled action (trace index)) →
      ∃ index, start ≤ index ∧ trace (index + 1) ≠ trace index) :
    ∃ index, final (trace index) :=
  eventuallyFinal trace rank final (fun state => ∃ action, enabled action state)
    step nonfinalEnables (familyFairness trace enabled eachFair)

end PeriScribe.RankedLiveness
