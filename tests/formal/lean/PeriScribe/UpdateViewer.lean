import Std

namespace PeriScribe.UpdateViewer

abbrev Key := Nat × Nat

structure Row where
  serial : Nat
  time : Int
  identifier : Option Nat
  name : Nat
  logged : Option Key
  area : Nat
  deriving DecidableEq, Repr

def identity (row : Row) : Key :=
  row.logged.getD
    (match row.identifier with | some id => (0, id) | none => (1, row.name))

def previous (history : List Row) (key : Key) : Option Nat :=
  (history.reverse.find? (fun row => identity row == key)).map (·.area)

def remember (ledger : Key → Option Nat) (row : Row) : Key → Option Nat :=
  fun key => if key = identity row then some row.area else ledger key

structure Update where
  row : Row
  baseline : Option Nat
  deriving DecidableEq, Repr

def changed (row : Row) (baseline : Option Nat) : Bool := row.area != baseline.getD 0

def collect (now width : Int) (ledger : Key → Option Nat) : List Row → List Update
  | [] => []
  | first :: rest =>
    if now < first.time then collect now width ledger rest
    else
      let baseline := ledger (identity first)
      let following := collect now width (remember ledger first) rest
      if now - width < first.time ∧ changed first baseline then
        ⟨first, baseline⟩ :: following
      else following

/-- The reference searches the complete retained prefix, independently of a ledger. -/
def reference (now width : Int) (history : List Row) : List Row → List Update
  | [] => []
  | first :: rest =>
    if now < first.time then reference now width history rest
    else
      let baseline := previous history (identity first)
      let following := reference now width (history ++ [first]) rest
      if now - width < first.time ∧ changed first baseline then
        ⟨first, baseline⟩ :: following
      else following

def chronological (rows : List Row) : List Row :=
  rows.mergeSort (fun first second => first.time ≤ second.time)

def snapshot (now width : Int) (rows : List Row) : List Update :=
  collect now width (fun _ => none) (chronological rows)

theorem logged_identity_has_priority (row : Row) (key : Key)
    (logged : row.logged = some key) : identity row = key := by simp [identity, logged]

theorem identifier_fallback (row : Row) (identifier : Nat)
    (missing : row.logged = none) (named : row.identifier = some identifier) :
    identity row = (0, identifier) := by simp [identity, missing, named]

theorem name_fallback (row : Row) (missing : row.logged = none)
    (unnamed : row.identifier = none) : identity row = (1, row.name) := by
  simp [identity, missing, unnamed]

theorem previous_append (history : List Row) (row : Row) (key : Key) :
    previous (history ++ [row]) key = remember (previous history) row key := by
  simp only [previous, List.reverse_append, List.reverse_singleton,
    List.singleton_append, List.find?_cons, remember]
  by_cases same : key = identity row
  · simp [same]
  · have different : identity row ≠ key := Ne.symm same
    have unequal : (identity row == key) = false := by simpa using different
    simp [same, unequal]

theorem ledger_equals_complete_prefix (now width : Int) (history rows : List Row) :
    collect now width (previous history) rows = reference now width history rows := by
  induction rows generalizing history with
  | nil => rfl
  | cons first rest induction =>
    simp only [collect, reference]
    split
    · exact induction history
    · have ledger : remember (previous history) first =
          previous (history ++ [first]) := by
        funext key
        exact (previous_append history first key).symm
      rw [ledger, induction]

theorem snapshot_equals_complete_history_reference (now width : Int) (rows : List Row) :
    snapshot now width rows = reference now width [] (chronological rows) := by
  have empty : previous [] = (fun _ => none) := by funext key; rfl
  rw [snapshot, ← empty]
  exact ledger_equals_complete_prefix now width [] (chronological rows)


theorem previous_has_same_identity_evidence (history : List Row) (key : Key)
    (area : Nat) (found : previous history key = some area) :
    ∃ row ∈ history, identity row = key ∧ row.area = area := by
  unfold previous at found
  cases result : history.reverse.find? (fun row => identity row == key) with
  | none => simp [result] at found
  | some row =>
    have present := List.mem_of_find?_eq_some result
    have matching := List.find?_some result
    simp only [result, Option.map_some, Option.some.injEq] at found
    exact ⟨row, by simpa using present, by simpa using matching, found⟩

theorem unrelated_history_does_not_change_baseline (history : List Row) (row : Row)
    (key : Key) (different : key ≠ identity row) :
    previous (history ++ [row]) key = previous history key := by
  simp [previous_append, remember, different]

theorem future_does_not_change_baseline_or_output (now width : Int)
    (ledger : Key → Option Nat) (row : Row) (rest : List Row)
    (future : now < row.time) :
    collect now width ledger (row :: rest) = collect now width ledger rest := by
  simp [collect, future]

theorem old_records_still_update_baseline (now width : Int)
    (ledger : Key → Option Nat) (row : Row) (rest : List Row)
    (old : row.time ≤ now - width) (notFuture : row.time ≤ now) :
    collect now width ledger (row :: rest) =
      collect now width (remember ledger row) rest := by
  simp [collect, show ¬ now < row.time by omega, show ¬ now - width < row.time by omega]

theorem unchanged_records_are_suppressed (now width : Int)
    (ledger : Key → Option Nat) (row : Row) (rest : List Row)
    (same : row.area = (ledger (identity row)).getD 0) (notFuture : row.time ≤ now) :
    collect now width ledger (row :: rest) =
      collect now width (remember ledger row) rest := by
  simp [collect, changed, same, show ¬ now < row.time by omega]

theorem emitted_records_are_true_window_changes (now width : Int)
    (ledger : Key → Option Nat) (rows : List Row) (update : Update)
    (emitted : update ∈ collect now width ledger rows) :
    update.row ∈ rows ∧ now - width < update.row.time ∧
      update.row.time ≤ now ∧ update.row.area ≠ update.baseline.getD 0 := by
  induction rows generalizing ledger with
  | nil => simp [collect] at emitted
  | cons first rest induction =>
    simp only [collect] at emitted
    split at emitted
    · obtain ⟨member, within, notFuture, changes⟩ := induction ledger emitted
      exact ⟨by simp [member], within, notFuture, changes⟩
    · rename_i notFuture
      split at emitted
      · rename_i condition
        rcases List.mem_cons.mp emitted with same | later
        · subst update
          exact ⟨by simp, condition.1, by change first.time ≤ now; omega,
            by simpa [changed] using condition.2⟩
        · obtain ⟨member, within, current, changes⟩ := induction _ later
          exact ⟨by simp [member], within, current, changes⟩
      · obtain ⟨member, within, current, changes⟩ := induction _ emitted
        exact ⟨by simp [member], within, current, changes⟩

theorem chronological_preserves_occurrences (rows : List Row) :
    (chronological rows).Perm rows := List.mergeSort_perm _ _

theorem chronological_is_ordered (rows : List Row) :
    (chronological rows).Pairwise (fun first second => first.time ≤ second.time) := by
  have sorted := List.pairwise_mergeSort
    (le := fun first second : Row => decide (first.time ≤ second.time))
    (by intro a b c first second; simp_all; omega)
    (by intro a b; simp; omega) rows
  simpa [chronological] using sorted

/-- Browser ages use milliseconds; bucket endpoints are independent of sorting. -/
def bucket (age : Int) : Option Nat :=
  if age < 0 ∨ 172800000 ≤ age then none
  else if age < 3600000 then some 0
  else if age < 14400000 then some 1
  else if age < 43200000 then some 2
  else if age < 86400000 then some 3
  else some 4

def bounds (index : Nat) : Int × Int :=
  match index with
  | 0 => (0, 3600000)
  | 1 => (3600000, 14400000)
  | 2 => (14400000, 43200000)
  | 3 => (43200000, 86400000)
  | _ => (86400000, 172800000)

theorem bucket_exists_exactly_in_window (age : Int) :
    (bucket age).isSome = true ↔ 0 ≤ age ∧ age < 172800000 := by
  grind [bucket]

theorem bucket_membership (age : Int) (index : Nat) :
    bucket age = some index ↔ index < 5 ∧
      (bounds index).1 ≤ age ∧ age < (bounds index).2 := by
  grind (splits := 20) [bucket, bounds]

theorem bucket_is_unique (age : Int) (first second : Nat)
    (one : bucket age = some first) (two : bucket age = some second) :
    first = second := by
  rw [one] at two
  exact Option.some.inj two

structure Visible where
  token : Nat
  owner : Key
  name : Nat
  age : Int
  matching : Bool
  deriving DecidableEq, Repr

def selected (index : Nat) (rows : List Visible) : List Visible :=
  rows.filter (fun row => row.matching && bucket row.age == some index)

def ordered (byName : Bool) (rows : List Visible) : List Visible :=
  rows.mergeSort (fun a b =>
    if byName ∧ a.name ≠ b.name then a.name ≤ b.name else a.age ≤ b.age)

theorem filtering_preserves_exact_multiplicity (index : Nat) (rows : List Visible)
    (row : Visible) :
    (selected index rows).count row =
      if row.matching && bucket row.age == some index then rows.count row else 0 := by
  by_cases passes : (row.matching && bucket row.age == some index) = true
  · simp only [selected, passes, ↓reduceIte]
    exact List.count_filter passes
  · have absent : row ∉ selected index rows := by simp [selected, passes]
    simp [List.count_eq_zero.mpr absent, passes]

theorem sorting_preserves_occurrences (byName : Bool) (rows : List Visible) :
    (ordered byName rows).Perm rows := List.mergeSort_perm _ _

theorem displayed_order_respects_name_then_time (byName : Bool) (rows : List Visible) :
    (ordered byName rows).Pairwise (fun a b =>
      if byName ∧ a.name ≠ b.name then a.name ≤ b.name else a.age ≤ b.age) := by
  have sorted := List.pairwise_mergeSort
    (le := fun a b : Visible =>
      decide (if byName ∧ a.name ≠ b.name then a.name ≤ b.name else a.age ≤ b.age))
    (by intro a b c first second; simp_all; grind)
    (by intro a b; simp; grind) rows
  simpa [ordered] using sorted


theorem sort_does_not_change_bucket_multiplicity (byName : Bool) (index : Nat)
    (rows : List Visible) (row : Visible) :
    (ordered byName (selected index rows)).count row =
      (selected index rows).count row :=
  (sorting_preserves_occurrences byName _).count_eq row

/-- Slots name prior DOM nodes; matching removes one occurrence, never a whole group. -/
abbrev Slot := Nat × Nat

def takeMatch (token : Nat) : List Slot → Option Slot × List Slot
  | [] => (none, [])
  | first :: rest =>
    if first.1 = token then (some first, rest)
    else
      let (found, remaining) := takeMatch token rest
      (found, first :: remaining)

def reconcile (old : List Slot) : List Nat → List (Nat × Option Nat)
  | [] => []
  | token :: rest =>
    let (found, remaining) := takeMatch token old
    (token, found.map (·.2)) :: reconcile remaining rest

theorem takeMatch_has_requested_signature (token : Nat) (old : List Slot) (slot : Slot)
    (found : (takeMatch token old).1 = some slot) : slot ∈ old ∧ slot.1 = token := by
  induction old with
  | nil => simp [takeMatch] at found
  | cons first rest induction =>
    simp only [takeMatch] at found
    split at found
    · simp only [Option.some.injEq] at found
      subst slot
      simp_all
    · obtain ⟨present, matching⟩ := induction found
      exact ⟨by simp [present], matching⟩

theorem takeMatch_preserves_other_slots (token : Nat) (old : List Slot) :
    ((takeMatch token old).1.toList ++ (takeMatch token old).2).Perm old := by
  induction old with
  | nil => simp [takeMatch]
  | cons first rest induction =>
    simp only [takeMatch]
    split
    · simp
    · cases found : takeMatch token rest with
      | mk chosen remaining =>
        simp only [found] at induction ⊢
        exact List.perm_middle.trans (List.Perm.cons first induction)

theorem replacement_preserves_requested_sequence (old : List Slot) (new : List Nat) :
    (reconcile old new).map (·.1) = new := by
  induction new generalizing old with
  | nil => rfl
  | cons first rest induction => simp [reconcile, induction]

theorem replacement_preserves_duplicate_count (old : List Slot) (new : List Nat)
    (token : Nat) : ((reconcile old new).map (·.1)).count token = new.count token := by
  rw [replacement_preserves_requested_sequence]


def retained (old : List Slot) (new : List Nat) : List Slot :=
  (reconcile old new).filterMap fun pair => pair.2.map fun node => (pair.1, node)

def remaining (old : List Slot) : List Nat → List Slot
  | [] => old
  | token :: rest => remaining (takeMatch token old).2 rest

theorem replacement_conserves_old_slots (old : List Slot) (new : List Nat) :
    (retained old new ++ remaining old new).Perm old := by
  induction new generalizing old with
  | nil => simp [retained, reconcile, remaining]
  | cons token rest induction =>
    have conserved := takeMatch_preserves_other_slots token old
    have tail := induction (takeMatch token old).2
    cases result : takeMatch token old with
    | mk chosen leftover =>
      simp only [result] at conserved tail
      cases chosen with
      | none =>
        simpa [retained, reconcile, remaining, result] using tail.trans conserved
      | some slot =>
        have matching := (takeMatch_has_requested_signature token old slot
          (by simp [result])).2
        have joined := (List.Perm.cons slot tail).trans conserved
        have shape : slot = (token, slot.2) := by ext <;> simp [matching]
        conv at joined => lhs; arg 1; rw [shape]
        simpa [retained, reconcile, remaining, result] using joined

theorem retained_slot_came_from_original (old : List Slot) (new : List Nat)
    (slot : Slot) (present : slot ∈ retained old new) : slot ∈ old :=
  (replacement_conserves_old_slots old new).mem_iff.mp (List.mem_append_left _ present)

theorem retained_node_is_never_reused_twice (old : List Slot) (new : List Nat)
    (unique : (old.map (·.2)).Nodup) :
    ((retained old new).map (·.2)).Nodup := by
  have perm := (replacement_conserves_old_slots old new).map (fun slot => slot.2)
  have all := perm.nodup_iff.mpr unique
  rw [List.map_append, List.nodup_append] at all
  exact all.1

def owners (rows : List Visible) : List Key := (rows.map (·.owner)).eraseDups

theorem count_owners_have_visible_evidence (rows : List Visible) (key : Key) :
    key ∈ owners rows ↔ ∃ row ∈ rows, row.owner = key := by
  simp [owners, List.mem_eraseDups]

theorem filtering_counts_exact_selected_identities (index : Nat)
    (rows : List Visible) (key : Key) :
    key ∈ owners (selected index rows) ↔ ∃ row ∈ rows,
      row.owner = key ∧ row.matching = true ∧ bucket row.age = some index := by
  simp [count_owners_have_visible_evidence, selected]
  grind

/-- Ownership changes grouping while every original observation remains intact. -/
abbrev Projection := Key → Option Key

def projectedIdentity (projection : Projection) (row : Row) : Key :=
  (projection (identity row)).getD (identity row)

structure ProjectedUpdate where
  row : Row
  owner : Key
  baseline : Option Nat
  deriving DecidableEq, Repr

def projectedPrevious (projection : Projection) (history : List Row)
    (key : Key) : Option Nat :=
  (history.reverse.find? (fun row => projectedIdentity projection row == key)).map
    (·.area)

def projectedRemember (projection : Projection) (ledger : Key → Option Nat)
    (row : Row) : Key → Option Nat :=
  fun key =>
    if key = projectedIdentity projection row then some row.area else ledger key

def projectedCollect (projection : Projection) (now width : Int)
    (ledger : Key → Option Nat) : List Row → List ProjectedUpdate
  | [] => []
  | first :: rest =>
    if now < first.time then projectedCollect projection now width ledger rest
    else
      let owner := projectedIdentity projection first
      let baseline := ledger owner
      let following := projectedCollect projection now width
        (projectedRemember projection ledger first) rest
      if now - width < first.time ∧ changed first baseline then
        ⟨first, owner, baseline⟩ :: following
      else following

/-- Search the retained raw prefix instead of maintaining an owner-indexed ledger. -/
def projectedReference (projection : Projection) (now width : Int)
    (history : List Row) : List Row → List ProjectedUpdate
  | [] => []
  | first :: rest =>
    if now < first.time then projectedReference projection now width history rest
    else
      let owner := projectedIdentity projection first
      let baseline := projectedPrevious projection history owner
      let following := projectedReference projection now width (history ++ [first]) rest
      if now - width < first.time ∧ changed first baseline then
        ⟨first, owner, baseline⟩ :: following
      else following

def projectedSnapshot (projection : Projection) (now width : Int)
    (rows : List Row) : List ProjectedUpdate :=
  projectedCollect projection now width (fun _ => none) (chronological rows)

theorem projected_identity_is_one_hop (projection : Projection) (row : Row) (key : Key)
    (assigned : projection (identity row) = some key) :
    projectedIdentity projection row = key := by simp [projectedIdentity, assigned]

theorem projected_identity_falls_back (projection : Projection) (row : Row)
    (missing : projection (identity row) = none) :
    projectedIdentity projection row = identity row := by
  simp [projectedIdentity, missing]

theorem projected_previous_append (projection : Projection) (history : List Row)
    (row : Row) (key : Key) :
    projectedPrevious projection (history ++ [row]) key =
      projectedRemember projection (projectedPrevious projection history) row key := by
  simp only [projectedPrevious, List.reverse_append, List.reverse_singleton,
    List.singleton_append, List.find?_cons, projectedRemember]
  by_cases same : key = projectedIdentity projection row
  · simp [same]
  · have unequal : (projectedIdentity projection row == key) = false := by
      simpa using Ne.symm same
    simp [same, unequal]

theorem projected_ledger_equals_complete_raw_prefix (projection : Projection)
    (now width : Int) (history rows : List Row) :
    projectedCollect projection now width (projectedPrevious projection history) rows =
      projectedReference projection now width history rows := by
  induction rows generalizing history with
  | nil => rfl
  | cons first rest ih =>
    simp only [projectedCollect, projectedReference]
    split
    · exact ih history
    · have ledger : projectedRemember projection (projectedPrevious projection history)
          first = projectedPrevious projection (history ++ [first]) := by
        funext key
        exact (projected_previous_append projection history first key).symm
      rw [ledger, ih]

theorem projected_snapshot_equals_complete_history_reference (projection : Projection)
    (now width : Int) (rows : List Row) :
    projectedSnapshot projection now width rows =
      projectedReference projection now width [] (chronological rows) := by
  have empty : projectedPrevious projection [] = (fun _ => none) := by funext key; rfl
  rw [projectedSnapshot, ← empty]
  exact projected_ledger_equals_complete_raw_prefix projection now width [] _

theorem absent_projection_refines_original_collector (now width : Int)
    (ledger : Key → Option Nat) (rows : List Row) :
    (projectedCollect (fun _ => none) now width ledger rows).map
      (fun update => ({ row := update.row, baseline := update.baseline } : Update)) =
      collect now width ledger rows := by
  induction rows generalizing ledger with
  | nil => rfl
  | cons first rest ih =>
    have rememberSame : projectedRemember (fun _ => none) ledger first =
        remember ledger first := rfl
    by_cases future : now < first.time
    · simpa [projectedCollect, collect, future] using ih ledger
    · by_cases emitted : now - width < first.time ∧
          changed first (ledger (identity first)) = true
      · simpa [projectedCollect, collect, projectedIdentity,
          rememberSame, future, emitted] using
          congrArg (fun tail => (⟨first, ledger (identity first)⟩ : Update) :: tail)
            (ih (remember ledger first))
      · simpa [projectedCollect, collect, projectedIdentity,
          rememberSame, future, emitted] using ih (remember ledger first)

theorem absent_projection_refines_original_snapshot (now width : Int)
    (rows : List Row) :
    (projectedSnapshot (fun _ => none) now width rows).map
      (fun update => ({ row := update.row, baseline := update.baseline } : Update)) =
      snapshot now width rows :=
  absent_projection_refines_original_collector now width _ _

theorem projected_baseline_has_original_evidence (projection : Projection)
    (history : List Row) (key : Key) (area : Nat)
    (found : projectedPrevious projection history key = some area) :
    ∃ row ∈ history, projectedIdentity projection row = key ∧ row.area = area := by
  unfold projectedPrevious at found
  cases result : history.reverse.find?
      (fun row => projectedIdentity projection row == key) with
  | none => simp [result] at found
  | some row =>
    have present := List.mem_of_find?_eq_some result
    have matching := List.find?_some result
    simp only [result, Option.map_some, Option.some.injEq] at found
    exact ⟨row, by simpa using present, by simpa using matching, found⟩

theorem latest_merged_record_supplies_baseline (projection : Projection)
    (history : List Row) (row : Row) (owner : Key)
    (same : projectedIdentity projection row = owner) :
    projectedPrevious projection (history ++ [row]) owner = some row.area := by
  simp [projected_previous_append, projectedRemember, same]

theorem other_projected_groups_cannot_change_baseline (projection : Projection)
    (history : List Row) (row : Row) (owner : Key)
    (different : owner ≠ projectedIdentity projection row) :
    projectedPrevious projection (history ++ [row]) owner =
      projectedPrevious projection history owner := by
  simp [projected_previous_append, projectedRemember, different]

theorem projected_future_does_not_change_baseline_or_output (projection : Projection)
    (now width : Int) (ledger : Key → Option Nat) (row : Row) (rest : List Row)
    (future : now < row.time) :
    projectedCollect projection now width ledger (row :: rest) =
      projectedCollect projection now width ledger rest := by
  simp [projectedCollect, future]

theorem old_projected_records_still_update_baseline (projection : Projection)
    (now width : Int) (ledger : Key → Option Nat) (row : Row) (rest : List Row)
    (old : row.time ≤ now - width) (notFuture : row.time ≤ now) :
    projectedCollect projection now width ledger (row :: rest) =
      projectedCollect projection now width (projectedRemember projection ledger row)
        rest := by
  simp [projectedCollect, show ¬ now < row.time by omega,
    show ¬ now - width < row.time by omega]

theorem unchanged_projected_records_are_suppressed (projection : Projection)
    (now width : Int) (ledger : Key → Option Nat) (row : Row) (rest : List Row)
    (same : row.area = (ledger (projectedIdentity projection row)).getD 0)
    (notFuture : row.time ≤ now) :
    projectedCollect projection now width ledger (row :: rest) =
      projectedCollect projection now width (projectedRemember projection ledger row)
        rest := by
  simp [projectedCollect, changed, same, show ¬ now < row.time by omega]

theorem projected_emission_preserves_raw_row_and_current_group (projection : Projection)
    (now width : Int) (ledger : Key → Option Nat) (rows : List Row)
    (update : ProjectedUpdate)
    (emitted : update ∈ projectedCollect projection now width ledger rows) :
    update.row ∈ rows ∧ update.owner = projectedIdentity projection update.row ∧
      now - width < update.row.time ∧ update.row.time ≤ now ∧
      update.row.area ≠ update.baseline.getD 0 := by
  induction rows generalizing ledger with
  | nil => simp [projectedCollect] at emitted
  | cons first rest ih =>
    simp only [projectedCollect] at emitted
    split at emitted
    · obtain ⟨present, owner, within, notFuture, change⟩ := ih ledger emitted
      exact ⟨by simp [present], owner, within, notFuture, change⟩
    · rename_i notFuture
      split at emitted
      · rename_i condition
        rcases List.mem_cons.mp emitted with same | later
        · subst update
          exact ⟨by simp, rfl, condition.1, by change first.time ≤ now; omega,
            by simpa [changed] using condition.2⟩
        · obtain ⟨present, owner, within, notFuture, change⟩ := ih _ later
          exact ⟨by simp [present], owner, within, notFuture, change⟩
      · obtain ⟨present, owner, within, notFuture, change⟩ := ih _ emitted
        exact ⟨by simp [present], owner, within, notFuture, change⟩

end PeriScribe.UpdateViewer
