import Std

namespace PeriScribe.IncrementalCollection

/-- Identifiers are unique in the current service view. Query predicates are
    evaluated against that same view; fetching is not a database snapshot protocol. -/
def candidates (current : List Nat) (changed missing flipped : Nat → Bool) : List Nat :=
  ((current.filter changed) ++ (current.filter missing) ++
    (current.filter flipped)).eraseDups

/-- Retrieve the union of three ID queries, then compare normalized content. -/
def collect (current : List Nat) (changed missing flipped different : Nat → Bool)
    (full : Bool) : List Nat :=
  let selected := if full then current else candidates current changed missing flipped
  (current.filter selected.contains).filter different

/-- Independent requirement: precisely the eligible, nonidentical rows. -/
def eligible (changed missing flipped : Nat → Bool) (full : Bool) (id : Nat) : Bool :=
  full || changed id || missing id || flipped id

theorem candidate_membership (current : List Nat) (changed missing flipped : Nat → Bool)
    (id : Nat) : id ∈ candidates current changed missing flipped ↔
      id ∈ current ∧ (changed id = true ∨ missing id = true ∨ flipped id = true) := by
  simp only [candidates, List.mem_eraseDups, List.mem_append, List.mem_filter]
  simp [and_or_left, or_assoc]

theorem collect_equals_declarative (current : List Nat)
    (changed missing flipped different : Nat → Bool) (full : Bool) :
    collect current changed missing flipped different full =
      current.filter (fun id =>
        eligible changed missing flipped full id && different id) := by
  unfold collect
  rw [List.filter_filter]
  apply List.filter_congr
  intro id member
  cases full <;> simp [eligible, candidate_membership, member]
  cases changed id <;> cases missing id <;> cases flipped id <;>
    cases different id <;> simp_all

theorem exact_membership (current : List Nat)
    (changed missing flipped different : Nat → Bool) (full : Bool) (id : Nat) :
    id ∈ collect current changed missing flipped different full ↔
      id ∈ current ∧ eligible changed missing flipped full id = true ∧
        different id = true := by
  rw [collect_equals_declarative]
  simp [List.mem_filter]

theorem collected_once (current : List Nat) (unique : current.Nodup)
    (changed missing flipped different : Nat → Bool) (full : Bool) :
    (collect current changed missing flipped different full).Nodup := by
  rw [collect_equals_declarative]
  exact unique.filter _

/-- This names the provider guarantee needed for incremental completeness.
    Backdated edits outside every route are deliberately not assumed covered. -/
theorem complete_for_observable_edits (current : List Nat)
    (changed missing flipped different : Nat → Bool)
    (observable : ∀ id ∈ current, different id = true →
      changed id = true ∨ missing id = true ∨ flipped id = true) :
    collect current changed missing flipped different false =
      current.filter different := by
  rw [collect_equals_declarative]
  apply List.filter_congr
  intro id member
  by_cases differs : different id = true
  · have routes := observable id member differs
    simpa [eligible, differs, Bool.or_eq_true, or_assoc] using routes
  · have same : different id = false := Bool.eq_false_iff.mpr differs
    simp [same]

theorem full_collects_all_differences (current : List Nat)
    (changed missing flipped different : Nat → Bool) :
    collect current changed missing flipped different true =
      current.filter different := by
  simp [collect_equals_declarative, eligible]

/-- Each change column contributes its own inclusive/null predicate. -/
def recent (cutoff : Int) (times : List (Option Int)) : Bool :=
  times.any fun time => match time with
    | none => true
    | some value => decide (cutoff ≤ value)

/-- Missing/unparseable stored timestamps do not contribute to the high water mark. -/
def cutoff (times : List (Option Int)) (overlap epoch : Int) : Int :=
  match times.filterMap id with
  | [] => epoch
  | first :: rest => rest.foldl max first - overlap

theorem empty_cutoff_uses_epoch (overlap epoch : Int) :
    cutoff [] overlap epoch = epoch := rfl

theorem singleton_cutoff (time overlap epoch : Int) :
    cutoff [some time] overlap epoch = time - overlap := rfl

theorem high_water_retains_initial (times : List Int) (initial : Int) :
    initial ≤ times.foldl max initial := by
  induction times generalizing initial with
  | nil => simp
  | cons first rest induction =>
    exact Int.le_trans (Int.le_max_left initial first) (induction (max initial first))

theorem high_water_covers_every_column (times : List Int) (initial value : Int)
    (present : value ∈ times) : value ≤ times.foldl max initial := by
  induction times generalizing initial with
  | nil => simp at present
  | cons first rest induction =>
    rcases List.mem_cons.mp present with same | later
    · subst first
      exact Int.le_trans (Int.le_max_right initial value)
        (high_water_retains_initial rest (max initial value))
    · exact induction (max initial first) later

theorem high_water_does_not_invent_future_time (times : List Int) (initial upper : Int)
    (initialBound : initial ≤ upper) (allBounded : ∀ value ∈ times, value ≤ upper) :
    times.foldl max initial ≤ upper := by
  induction times generalizing initial with
  | nil => exact initialBound
  | cons first rest induction =>
    exact induction (max initial first)
      (Int.max_le.mpr ⟨initialBound, allBounded first (by simp)⟩)
      (fun value member => allBounded value (by simp [member]))

theorem any_null_is_collected (cutoff : Int) (times : List (Option Int))
    (missing : none ∈ times) : recent cutoff times = true := by
  apply List.any_eq_true.mpr
  exact ⟨none, missing, rfl⟩

theorem overlap_is_inclusive (latest overlap value : Int) (times : List (Option Int))
    (present : some value ∈ times) (inWindow : latest - overlap ≤ value) :
    recent (latest - overlap) times = true := by
  apply List.any_eq_true.mpr
  exact ⟨some value, present, by simp [inWindow]⟩

def shouldQuery (full sameMetadataSnapshot : Bool) : Bool :=
  full || !sameMetadataSnapshot

theorem full_bypasses_metadata (same : Bool) : shouldQuery true same = true := by
  simp [shouldQuery]

theorem skip_requires_metadata_match (full same : Bool)
    (skip : shouldQuery full same = false) : full = false ∧ same = true := by
  cases full <;> cases same <;> simp_all [shouldQuery]

/-- Normalized row contents abstract shared attributes and geometry equivalence. -/
structure Row where
  id : Nat
  name : Nat
  active : Bool
  modified : Option Int
  geometry : Nat
  deriving BEq, DecidableEq, Repr

def storedRow (stored : List Row) (id : Nat) : Option Row :=
  stored.find? (fun row => row.id == id)

def select (stored current : List Row) (cutoff : Int) (full : Bool) : List Nat :=
  let identifiers := current.map Row.id
  let currentRow := fun id => current.find? (fun row => row.id == id)
  let changed := fun id => (currentRow id).any (fun row => recent cutoff [row.modified])
  let missing := fun id => (storedRow stored id).isNone
  let knownInactive := stored.any (fun row => !row.active)
  let flipped := fun id => knownInactive &&
    (storedRow stored id).any Row.active && (currentRow id).any (fun row => !row.active)
  let different := fun id => currentRow id != storedRow stored id
  collect identifiers changed missing flipped different full

end PeriScribe.IncrementalCollection
