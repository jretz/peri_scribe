namespace PeriScribe.ReplayPrefixes

/-- Replay continuity includes both durable files and compatible surviving TLC paths. -/
structure State (Filesystem : Type u) (Path : Type v) where
  filesystem : Filesystem
  compatiblePath : Path

/-- An assertion failure stops the complete history, including every later input. -/
def run (step : State Filesystem Path → Input → Option (State Filesystem Path))
    (initial : State Filesystem Path) : List Input → Option (State Filesystem Path)
  | [] => some initial
  | input :: rest => (step initial input).bind (fun next => run step next rest)

theorem run_append
    (step : State Filesystem Path → Input → Option (State Filesystem Path))
    (initial : State Filesystem Path) (leading trailing : List Input) :
    run step initial (leading ++ trailing) =
      (run step initial leading).bind (fun cached => run step cached trailing) := by
  induction leading generalizing initial with
  | nil => rfl
  | cons input rest induction =>
    simp only [List.cons_append, run]
    cases outcome : step initial input with
    | none => simp
    | some next => simpa [outcome] using induction next

theorem failed_prefix_rejects_complete_history
    (step : State Filesystem Path → Input → Option (State Filesystem Path))
    (initial : State Filesystem Path) (leading trailing : List Input)
    (failed : run step initial leading = none) :
    run step initial (leading ++ trailing) = none := by
  rw [run_append, failed]
  rfl

/-- Exact copy equivalence is an implementation obligation checked at the file boundary. -/
theorem copied_successful_prefix_preserves_complete_result
    (step : State Filesystem Path → Input → Option (State Filesystem Path))
    (initial cached copied : State Filesystem Path) (leading trailing : List Input)
    (succeeded : run step initial leading = some cached) (copy : copied = cached) :
    run step copied trailing = run step initial (leading ++ trailing) := by
  rw [run_append, succeeded, copy]
  rfl

theorem copied_suffix_failure_rejects_complete_history
    (step : State Filesystem Path → Input → Option (State Filesystem Path))
    (initial cached copied : State Filesystem Path) (leading trailing : List Input)
    (succeeded : run step initial leading = some cached) (copy : copied = cached)
    (failed : run step copied trailing = none) :
    run step initial (leading ++ trailing) = none := by
  rw [← copied_successful_prefix_preserves_complete_result
    step initial cached copied leading trailing succeeded copy]
  exact failed

end PeriScribe.ReplayPrefixes
