import PeriScribe.Geography

namespace PeriScribe.DifferentialRows

abbrev Shape := List Nat

def intersection (first second : Shape) : Shape :=
  first.filter (fun cell => second.contains cell)

def corrected (shapes : List Shape) : List Shape :=
  Geography.reverseCombine intersection shapes

theorem correction_uses_every_later_footprint (shapes : List Shape) :
    (corrected shapes).map (fun shape cell => cell ∈ shape) =
      Geography.corrected (shapes.map (fun shape cell => cell ∈ shape)) := by
  rw [corrected, Geography.concrete_recurrence_refines_set_recurrence]
  · exact Geography.reverse_recurrence_matches_all_later_intersections _
  · intro first second
    funext cell
    exact propext (by simp [intersection])

structure Source where
  identity : Nat
  time : Option Int
  values : Nat → Option Int

structure Step where
  position : Nat
  source : Source
  ring : Shape
  candidate : Bool
  emitted : Bool

/-- Omission models a constructed numerical sliver without erasing source evidence. -/
def annotate (position : Nat) (previous : Shape) (omitted : List Nat) :
    List (Source × Shape) → List Step
  | [] => []
  | (source, shape) :: rest =>
    let ring := (shape.filter (fun cell => !previous.contains cell)).eraseDups
    ⟨position, source, ring, !ring.isEmpty, !omitted.contains position⟩ ::
      annotate (position + 1) shape omitted rest

structure Group where
  start : Nat
  last : Nat
  source : Source
  ring : Shape
  emitted : Bool

/-- Every no-growth observation updates the preceding ring's representative metadata. -/
def groupStep (groups : List Group) (step : Step) : List Group :=
  if step.candidate then
    ⟨step.position, step.position, step.source, step.ring, step.emitted⟩ :: groups
  else match groups with
    | [] => []
    | previous :: rest =>
      { previous with last := step.position, source := step.source } :: rest

def groups (steps : List Step) : List Group := (steps.foldl groupStep []).reverse

theorem no_growth_keeps_ring_and_updates_representative (previous : Group)
    (rest : List Group) (step : Step) (noGrowth : step.candidate = false) :
    (groupStep (previous :: rest) step).head?.map (fun group =>
      (group.start, group.last, group.source.identity, group.ring)) =
      some (previous.start, step.position, step.source.identity, previous.ring) := by
  simp [groupStep, noGrowth]

theorem growth_starts_a_new_representative (groups : List Group) (step : Step)
    (grows : step.candidate = true) :
    (groupStep groups step).head?.map (fun group => (group.start, group.last)) =
      some (step.position, step.position) := by simp [groupStep, grows]

theorem no_growth_block_preserves_candidate (previous : Group) (rest : List Group)
    (steps : List Step) (noGrowth : ∀ step ∈ steps, step.candidate = false) :
    ∃ source position, steps.foldl groupStep (previous :: rest) =
      { previous with source := source, last := position } :: rest := by
  induction steps generalizing previous with
  | nil => exact ⟨previous.source, previous.last, rfl⟩
  | cons step tail induction =>
    have first := noGrowth step (by simp)
    have remaining : ∀ entry ∈ tail, entry.candidate = false := by
      intro entry member
      exact noGrowth entry (by simp [member])
    simpa [List.foldl_cons, groupStep, first] using
      induction { previous with source := step.source, last := step.position } remaining

theorem whole_block_selects_last_observation (previous : Group) (rest : List Group)
    (middle : List Step) (last : Step)
    (noGrowth : ∀ step ∈ middle ++ [last], step.candidate = false) :
    (middle ++ [last]).foldl groupStep (previous :: rest) =
      { previous with source := last.source, last := last.position } :: rest := by
  have middleNoGrowth : ∀ step ∈ middle, step.candidate = false := by
    intro step member
    exact noGrowth step (by simp [member])
  rcases no_growth_block_preserves_candidate previous rest middle middleNoGrowth with
    ⟨source, position, folded⟩
  have finalNoGrowth := noGrowth last (by simp)
  simp [List.foldl_append, folded, groupStep, finalNoGrowth]

def supported (steps : List Step) (group : Group) : Prop :=
  ∃ step ∈ steps, group.source = step.source ∧ group.last = step.position

theorem group_step_preserves_metadata_witness (previous : List Group) (step : Step)
    (group : Group) (member : group ∈ groupStep previous step) :
    supported [step] group ∨ group ∈ previous := by
  unfold groupStep at member
  split at member
  · rcases List.mem_cons.mp member with same | old
    · subst group
      exact Or.inl ⟨step, by simp, rfl, rfl⟩
    · exact Or.inr old
  · cases previous with
    | nil => simp at member
    | cons old rest =>
      rcases List.mem_cons.mp member with same | unchanged
      · subst group
        exact Or.inl ⟨step, by simp, rfl, rfl⟩
      · exact Or.inr (List.mem_cons_of_mem _ unchanged)

theorem group_fold_preserves_metadata_witness (steps history : List Step)
    (previous : List Group) (valid : ∀ group ∈ previous, supported history group) :
    ∀ group ∈ steps.foldl groupStep previous, supported (history ++ steps) group := by
  induction steps generalizing history previous with
  | nil => simpa using valid
  | cons step rest induction =>
    intro group member
    have nextValid : ∀ group ∈ groupStep previous step,
        supported (history ++ [step]) group := by
      intro selected present
      rcases group_step_preserves_metadata_witness previous step selected present with
        ⟨witness, included, same, index⟩ | old
      · exact ⟨witness, by simp [included], same, index⟩
      · rcases valid selected old with ⟨witness, included, same, index⟩
        exact ⟨witness, by simp [included], same, index⟩
    simpa [List.append_assoc] using
      induction (history ++ [step]) (groupStep previous step) nextValid group member

theorem every_representative_has_original_metadata (steps : List Step) :
    ∀ group ∈ groups steps, supported steps group := by
  intro group member
  have present : group ∈ steps.foldl groupStep [] := by simpa [groups] using member
  simpa using group_fold_preserves_metadata_witness steps [] [] (by simp) group present

/-- Increasing candidate boundaries select a representative within the same block. -/
def representativeIndex (count : Nat) (next : Option Nat) : Nat := next.getD count - 1

theorem representative_stays_in_its_block (start stop count : Nat)
    (afterStart : start < stop) (bounded : stop ≤ count) :
    start ≤ representativeIndex count (some stop) ∧
      representativeIndex count (some stop) < count := by
  simp only [representativeIndex, Option.getD_some]
  omega

def firstPresent : List (Option Int) → Option Int
  | [] => none
  | none :: rest => firstPresent rest
  | some value :: _ => some value

theorem previous_value_has_a_first_present_witness (history : List (Option Int))
    (value : Int) (selected : firstPresent history = some value) :
    ∃ absent rest, history = List.replicate absent none ++ some value :: rest := by
  induction history with
  | nil => simp [firstPresent] at selected
  | cons first rest induction =>
    cases first with
    | none =>
      rcases induction selected with ⟨absent, tail, same⟩
      exact ⟨absent + 1, tail, by simp [List.replicate_succ, same]⟩
    | some current =>
      have same : current = value := by simpa [firstPresent] using selected
      subst current
      exact ⟨0, rest, rfl⟩

def difference (current : Option Int) (previous : List (Option Int)) : Option Int :=
  current.map (fun value => value - (firstPresent previous).getD 0)

theorem missing_measurement_stays_missing (previous : List (Option Int)) :
    difference none previous = none := rfl

theorem difference_uses_latest_present_value (current previous : Int)
    (absent : Nat) (older : List (Option Int)) :
    difference (some current) (List.replicate absent none ++ some previous :: older) =
      some (current - previous) := by
  induction absent with
  | zero => rfl
  | succ count induction =>
    simpa [List.replicate_succ, difference, firstPresent] using induction

def completeChanges (previous : Int) : List (Option Int) → List Int
  | [] => []
  | none :: rest => completeChanges previous rest
  | some current :: rest => (current - previous) :: completeChanges current rest

def latestValue (previous : Int) : List (Option Int) → Int
  | [] => previous
  | none :: rest => latestValue previous rest
  | some current :: rest => latestValue current rest

theorem complete_changes_telescope (previous : Int) (values : List (Option Int)) :
    (completeChanges previous values).sum + previous = latestValue previous values := by
  induction values generalizing previous with
  | nil => simp [completeChanges, latestValue]
  | cons current rest induction =>
    cases current with
    | none => exact induction previous
    | some current =>
      simp only [completeChanges, latestValue, List.sum_cons]
      have final := induction current
      omega

structure Row where
  group : Group
  differences : Nat → Option Int

def candidateRows (previous : List Group) : List Group → List Row
  | [] => []
  | current :: rest =>
    ⟨current, fun key => difference (current.source.values key)
      (previous.map (fun group => group.source.values key))⟩ ::
      candidateRows (current :: previous) rest

def emitted (rows : List Row) : List Row := rows.filter (fun row => row.group.emitted)

theorem candidate_rows_keep_group_order (previous current : List Group) :
    (candidateRows previous current).map Row.group = current := by
  induction current generalizing previous with
  | nil => rfl
  | cons first rest induction => simp [candidateRows, induction]

theorem emitting_does_not_modify_candidate_differences (rows : List Row) (row : Row)
    (member : row ∈ emitted rows) : row ∈ rows ∧ row.group.emitted = true := by
  exact List.mem_filter.mp member

def visible (minimum : Nat) (area : Shape → Nat) (rows : List Row) : List Row :=
  (emitted rows).filter (fun row => row.group.source.time.isSome &&
    decide (minimum < area row.group.ring))

def visibleSequence (minimum : Nat) (area : Shape → Nat)
    (rows : List Row) : List Shape :=
  (visible minimum area rows).map (fun row => row.group.ring)

theorem displayed_sequence_has_exact_visible_witness (minimum : Nat)
    (area : Shape → Nat) (rows : List Row) (shape : Shape) :
    shape ∈ visibleSequence minimum area rows ↔
      ∃ row ∈ rows, row.group.emitted = true ∧ row.group.source.time.isSome = true ∧
        minimum < area row.group.ring ∧ row.group.ring = shape := by
  simp [visibleSequence, visible, emitted, and_assoc, and_left_comm, and_comm]

theorem visibility_preserves_order (minimum : Nat) (area : Shape → Nat)
    (rows : List Row) : (visible minimum area rows).Sublist rows :=
  List.filter_sublist.trans List.filter_sublist

def build (sources : List Source) (shapes : List Shape)
    (omitted : List Nat) : List Row :=
  candidateRows [] (groups (annotate 0 [] omitted (sources.zip (corrected shapes))))

end PeriScribe.DifferentialRows
