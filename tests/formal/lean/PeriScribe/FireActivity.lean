import Std

namespace PeriScribe.FireActivity

/-- Exact acres and signed elapsed seconds abstract unit and clock adapters. -/
structure Observation where
  time : Int
  area : Nat
  deriving Repr, DecidableEq

/-- Source order resolves an equal-time correction in favor of its last sample. -/
def lastSamples : List Observation → List Observation
  | [] => []
  | first :: rest =>
    if rest.any (fun row => row.time == first.time) then lastSamples rest
    else first :: lastSamples rest

/-- Exclude future evidence before selecting equal-time corrections. -/
def visible (reference : Int) (rows : List Observation) : List Observation :=
  lastSamples (rows.filter (fun row => row.time ≤ reference))

/-- Select the greatest eligible timestamp independently of input ordering. -/
def baseline (cutoff : Int) : List Observation → Option Observation
  | [] => none
  | first :: rest =>
    match baseline cutoff rest with
    | none => if first.time ≤ cutoff then some first else none
    | some selected =>
      if first.time ≤ cutoff ∧ selected.time < first.time then some first
      else some selected

/-- A peak counts a rebound once and never turns a decrease into growth. -/
def peak (initial : Nat) (rows : List Observation) : Nat :=
  rows.foldl (fun area row => max area row.area) initial

/-- A missing baseline has a separate meaning from measured zero growth. -/
def window (reference width : Int) (rows : List Observation) : Option (Nat × Nat) :=
  let past := visible reference rows
  let cutoff := reference - width
  (baseline cutoff past).map fun selected =>
    (selected.area,
      peak selected.area (past.filter (fun row => cutoff < row.time)) - selected.area)

/-- Cross multiplication preserves strict half-percent boundaries in exact acres. -/
def shortSignal (measurement : Nat × Nat) : Bool :=
  decide (10 < measurement.2 ∧ measurement.1 < 200 * measurement.2)

/-- Either cumulative route requires the independent ten-acre noise floor. -/
def longSignal (measurement : Nat × Nat) : Bool :=
  decide (10 < measurement.2 ∧
    (25 < measurement.2 ∨ measurement.1 < 100 * measurement.2))

def shortWidth : Int := 259200
def longWidth : Int := 604800

/-- Initial grace belongs only to a nonempty stream lacking a short baseline. -/
def streamActive (reference : Int) (rows : List Observation) : Bool :=
  if (visible reference rows).isEmpty then false
  else match window reference shortWidth rows with
    | none => true
    | some measured => shortSignal measured ||
      ((window reference longWidth rows).map longSignal).getD false

inductive Status where
  | inactive
  | active
  | holding
  deriving Repr, DecidableEq

/-- Source inactivity wins; otherwise unknown evidence and either stream can retain Active. -/
def status (sourceActive : Bool) (reference : Int)
    (reported mapped : List Observation) : Status :=
  if !sourceActive then .inactive
  else if (visible reference reported).isEmpty && (visible reference mapped).isEmpty
    then .active
  else if streamActive reference reported || streamActive reference mapped
    then .active
  else .holding

theorem last_samples_single_time (time : Int) (first last : Nat) :
    lastSamples [⟨time, first⟩, ⟨time, last⟩] = [⟨time, last⟩] := by
  simp [lastSamples]

theorem baseline_is_past (cutoff : Int) (rows : List Observation)
    (selected : Observation) (found : baseline cutoff rows = some selected) :
    selected ∈ rows ∧ selected.time ≤ cutoff := by
  induction rows generalizing selected with
  | nil => simp [baseline] at found
  | cons first rest induction =>
    simp only [baseline] at found
    cases previous : baseline cutoff rest with
    | none =>
      simp only [previous] at found
      split at found
      · simp only [Option.some.injEq] at found
        subst selected
        simp_all
      · simp at found
    | some row =>
      simp only [previous] at found
      split at found
      · simp only [Option.some.injEq] at found
        subst selected
        simp_all
      · simp only [Option.some.injEq] at found
        subst selected
        obtain ⟨member, past⟩ := induction row previous
        exact ⟨List.mem_cons_of_mem _ member, past⟩

theorem baseline_none_is_all_future (cutoff : Int) (rows : List Observation)
    (missing : baseline cutoff rows = none) (row : Observation) (member : row ∈ rows) :
    cutoff < row.time := by
  induction rows with
  | nil => simp at member
  | cons first rest induction =>
    simp only [baseline] at missing
    cases previous : baseline cutoff rest with
    | none =>
      simp only [previous] at missing
      split at missing
      · simp at missing
      · rename_i after
        rcases List.mem_cons.mp member with same | later
        · subst row; omega
        · exact induction previous later
    | some selected =>
      simp only [previous] at missing
      split at missing <;> simp at missing

theorem baseline_is_latest (cutoff : Int) (rows : List Observation)
    (selected candidate : Observation) (found : baseline cutoff rows = some selected)
    (member : candidate ∈ rows) (past : candidate.time ≤ cutoff) :
    candidate.time ≤ selected.time := by
  induction rows generalizing selected candidate with
  | nil => simp at member
  | cons first rest induction =>
    simp only [baseline] at found
    cases previous : baseline cutoff rest with
    | none =>
      simp only [previous] at found
      split at found
      · simp only [Option.some.injEq] at found
        subst selected
        rcases List.mem_cons.mp member with same | later
        · subst candidate; omega
        · have := baseline_none_is_all_future cutoff rest previous candidate later
          omega
      · simp at found
    | some row =>
      simp only [previous] at found
      split at found
      · rename_i condition
        simp only [Option.some.injEq] at found
        subst selected
        rcases List.mem_cons.mp member with same | later
        · subst candidate; omega
        · have before := induction row candidate previous later past
          omega
      · rename_i condition
        simp only [Option.some.injEq] at found
        subst selected
        rcases List.mem_cons.mp member with same | later
        · subst candidate; omega
        · exact induction row candidate previous later past

theorem visible_ignores_future (reference : Int) (rows future : List Observation)
    (later : ∀ row ∈ future, reference < row.time) :
    visible reference (rows ++ future) = visible reference rows := by
  have filtered : future.filter (fun row => row.time ≤ reference) = [] := by
    apply List.filter_eq_nil_iff.mpr
    intro row member
    have := later row member
    simp_all
  simp [visible, List.filter_append, filtered]

theorem window_ignores_future (reference width : Int) (rows future : List Observation)
    (later : ∀ row ∈ future, reference < row.time) :
    window reference width (rows ++ future) = window reference width rows := by
  simp only [window, visible_ignores_future reference rows future later]

theorem stream_ignores_future (reference : Int) (rows future : List Observation)
    (later : ∀ row ∈ future, reference < row.time) :
    streamActive reference (rows ++ future) = streamActive reference rows := by
  simp only [streamActive, visible_ignores_future reference rows future later,
    window_ignores_future reference shortWidth rows future later,
    window_ignores_future reference longWidth rows future later]

theorem status_ignores_future (sourceActive : Bool) (reference : Int)
    (reported mapped reportFuture mapFuture : List Observation)
    (reportLater : ∀ row ∈ reportFuture, reference < row.time)
    (mapLater : ∀ row ∈ mapFuture, reference < row.time) :
    status sourceActive reference (reported ++ reportFuture) (mapped ++ mapFuture) =
      status sourceActive reference reported mapped := by
  simp only [status, visible_ignores_future reference reported reportFuture reportLater,
    visible_ignores_future reference mapped mapFuture mapLater,
    stream_ignores_future reference reported reportFuture reportLater,
    stream_ignores_future reference mapped mapFuture mapLater]

theorem inactive_source_has_priority (reference : Int)
    (reported mapped : List Observation) :
    status false reference reported mapped = .inactive := by simp [status]

theorem unknown_stays_active (reference : Int) (reported mapped : List Observation)
    (noReported : visible reference reported = [])
    (noMapped : visible reference mapped = []) :
    status true reference reported mapped = .active := by simp [status, noReported, noMapped]

theorem short_grace_is_active (reference : Int) (rows : List Observation)
    (known : (visible reference rows).isEmpty = false)
    (missing : window reference shortWidth rows = none) :
    streamActive reference rows = true := by simp [streamActive, known, missing]

theorem short_thresholds_are_strict (baseline growth : Nat) :
    shortSignal (baseline, growth) = true ↔ 10 < growth ∧ baseline < 200 * growth := by
  simp [shortSignal]

theorem long_thresholds_are_strict (baseline growth : Nat) :
    longSignal (baseline, growth) = true ↔
      10 < growth ∧ (25 < growth ∨ baseline < 100 * growth) := by
  simp [longSignal]

theorem long_area_route (baseline growth : Nat) (large : 25 < growth) :
    longSignal (baseline, growth) = true := by simp [longSignal]; omega

theorem long_percentage_route (baseline growth : Nat)
    (noise : 10 < growth) (relative : baseline < 100 * growth) :
    longSignal (baseline, growth) = true := by simp [longSignal, noise, relative]

theorem neither_signal_has_no_long_grace (reference : Int) (rows : List Observation)
    (measured : Nat × Nat) (known : (visible reference rows).isEmpty = false)
    (shortKnown : window reference shortWidth rows = some measured)
    (quiet : shortSignal measured = false)
    (longMissing : window reference longWidth rows = none) :
    streamActive reference rows = false := by
  simp [streamActive, known, shortKnown, quiet, longMissing]

theorem no_updates_yields_zero (reference width : Int) (rows : List Observation)
    (selected : Observation) (found : baseline (reference - width)
      (visible reference rows) = some selected)
    (noLater : (visible reference rows).filter
      (fun row => reference - width < row.time) = []) :
    window reference width rows = some (selected.area, 0) := by
  simp [window, found, noLater, peak]

end PeriScribe.FireActivity
