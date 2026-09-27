import Std

namespace PeriScribe.BorderClassification

/-- A finite exact footprint, with duplicate cells removed before any measurement. -/
def unionCells (parts : List (List Nat)) : List Nat := parts.flatten.eraseDups

theorem union_membership (parts : List (List Nat)) (cell : Nat) :
    cell ∈ unionCells parts ↔ ∃ part ∈ parts, cell ∈ part := by
  simp [unionCells]

theorem duplicate_parts_do_not_change_membership (parts : List (List Nat))
    (part : List Nat) (cell : Nat) :
    cell ∈ unionCells (part :: part :: parts) ↔
      cell ∈ unionCells (part :: parts) := by simp [unionCells]

theorem one_sided_union_stays_on_that_side (parts : List (List Nat))
    (side : Nat → Prop) (allParts : ∀ part ∈ parts, ∀ cell ∈ part, side cell) :
    ∀ cell ∈ unionCells parts, side cell := by
  intro cell present
  rcases (union_membership parts cell).mp present with ⟨part, member, inside⟩
  exact allParts part member cell inside

theorem deduplicated_cells_are_unique (cells : List Nat) : cells.eraseDups.Nodup := by
  cases cells with
  | nil => simp
  | cons first rest =>
    rw [List.eraseDups_cons]
    apply List.nodup_cons.mpr
    constructor
    · simp
    · exact deduplicated_cells_are_unique (rest.filter (fun cell => !cell == first))
termination_by cells.length
decreasing_by
  have bound := List.length_filter_le (fun cell => !cell == first) rest
  simp only [List.length_cons]
  omega

theorem union_counts_each_cell_at_most_once (parts : List (List Nat)) (cell : Nat) :
    (unionCells parts).count cell ≤ 1 := by
  exact List.nodup_iff_count.mp (deduplicated_cells_are_unique parts.flatten) cell

structure Geometry where
  crosses : Bool
  near : Bool
  inside : Bool
  deriving Repr, DecidableEq

/-- Ratios are cross multiplied; zero-area footprints do not invent fractions. -/
def geometry (total inside distance buffer fraction absolute majority : Nat) :
    Geometry :=
  let outside := total - inside
  let crosses := decide (0 < total ∧ 0 < inside ∧
    (fraction * total < 100 * outside ∨ absolute < outside))
  ⟨crosses, !crosses && decide (distance ≤ buffer),
    decide ((total = 0 ∧ majority = 0) ∨
      (0 < total ∧ majority * total ≤ 100 * inside))⟩

/-- The optimized exterior path measures the set union, preserving overlapping area. -/
def exterior (distance buffer majority : Nat) : Geometry :=
  ⟨false, decide (distance ≤ buffer), decide (majority = 0)⟩

theorem exterior_optimization_preserves_decisions
    (total distance buffer fraction absolute majority : Nat) :
    geometry total 0 distance buffer fraction absolute majority =
      exterior distance buffer majority := by
  simp only [geometry, exterior, Nat.sub_zero, Nat.mul_zero, Nat.not_lt_zero,
    and_false, false_and, decide_false, Bool.not_false, Bool.true_and]
  congr 1
  congr 1
  apply propext
  constructor
  · rintro (⟨_, zero⟩ | ⟨positive, bound⟩)
    · exact zero
    · exact (Nat.mul_eq_zero.mp (Nat.eq_zero_of_le_zero bound)).resolve_right (by omega)
  · intro zero
    by_cases empty : total = 0
    · exact Or.inl ⟨empty, zero⟩
    · exact Or.inr ⟨by omega, by simp [zero]⟩

theorem zero_area_inside_iff_zero_threshold
    (distance buffer fraction absolute majority : Nat) :
    (geometry 0 0 distance buffer fraction absolute majority).inside = true ↔
      majority = 0 := by simp [geometry]

theorem crossing_has_inside_and_outside_evidence
    (total inside distance buffer fraction absolute majority : Nat)
    (crossing : Geometry.crosses
      (geometry total inside distance buffer fraction absolute majority) = true) :
    0 < inside ∧ 0 < total - inside := by
  simp only [geometry, decide_eq_true_eq] at crossing
  rcases crossing with ⟨_, positive, smaller | larger⟩ <;>
    exact ⟨positive, by omega⟩

theorem crossing_is_not_only_near
    (total inside distance buffer fraction absolute majority : Nat)
    (crossing : Geometry.crosses
      (geometry total inside distance buffer fraction absolute majority) = true) :
    (geometry total inside distance buffer fraction absolute majority).near = false :=
    by
  simp only [geometry] at crossing ⊢
  rw [crossing]
  rfl

/-- Inside, inside-near, crossing, outside-near, outside are distinct output states. -/
def classify (signal : Geometry) (extent : Bool) : Nat :=
  if signal.crosses then 2
  else if signal.near || extent then if signal.inside then 1 else 3
  else if signal.inside then 0 else 4

def evidence (signal : Geometry) (extent identifier : Bool) : List Nat :=
  (if signal.crosses then [0] else []) ++
    (if signal.near then [1] else []) ++
    (if extent then [2] else []) ++ (if identifier then [3] else [])

def preferWfigs (classification : Nat) : Bool :=
  classification == 2 || classification == 3 || classification == 4

theorem only_geometry_authorizes_crossing (signal : Geometry) (extent : Bool) :
    classify signal extent = 2 ↔ signal.crosses = true := by
  rcases signal with ⟨crosses, near, inside⟩
  cases crosses <;> cases near <;> cases inside <;> cases extent <;> decide

theorem identifier_is_only_evidence (signal : Geometry) (extent identifier : Bool) :
    3 ∈ evidence signal extent identifier ↔ identifier = true := by
  rcases signal with ⟨crosses, near, inside⟩
  cases crosses <;> cases near <;> cases extent <;> cases identifier <;>
    simp [evidence]

theorem inside_without_crossing_prefers_firis (signal : Geometry) (extent : Bool)
    (inside : signal.inside = true) (notCrossing : signal.crosses = false) :
    preferWfigs (classify signal extent) = false := by
  simp [classify, inside, notCrossing, preferWfigs]
  split <;> decide

theorem crossing_prefers_wfigs (signal : Geometry) (extent : Bool)
    (crossing : signal.crosses = true) :
    preferWfigs (classify signal extent) = true := by
  simp [classify, crossing, preferWfigs]

structure Extent where
  time : Option Nat
  serial : Nat
  area : Nat
  shape : Nat
  deriving Repr

def recency (value : Extent) : Nat × Nat :=
  ((value.time.map (· + 1)).getD 0, value.serial)

def earlier (first second : Extent) : Prop :=
  (recency first).1 < (recency second).1 ∨
    ((recency first).1 = (recency second).1 ∧ first.serial < second.serial)

instance (first second : Extent) : Decidable (earlier first second) :=
  inferInstanceAs (Decidable (_ ∨ _))

def dominates (winner other : Extent) : Prop :=
  (recency other).1 < (recency winner).1 ∨
    ((recency other).1 = (recency winner).1 ∧ other.serial ≤ winner.serial)

def freshest : List Extent → Option Extent
  | [] => none
  | first :: rest => match freshest rest with
    | none => some first
    | some winner => some (if earlier first winner then winner else first)

theorem freshest_is_existing_evidence (values : List Extent) (winner : Extent)
    (selected : freshest values = some winner) : winner ∈ values := by
  induction values with
  | nil => simp [freshest] at selected
  | cons first rest induction =>
    simp only [freshest] at selected
    split at selected
    · cases Option.some.inj selected
      simp
    next candidate found =>
      split at selected
      · cases Option.some.inj selected
        exact List.mem_cons_of_mem _ (induction found)
      · cases Option.some.inj selected
        simp

theorem freshest_is_maximal (values : List Extent) (winner : Extent)
    (selected : freshest values = some winner) :
    ∀ other ∈ values, dominates winner other := by
  induction values generalizing winner with
  | nil => simp [freshest] at selected
  | cons first rest induction =>
    simp only [freshest] at selected
    split at selected
    next missing =>
      cases Option.some.inj selected
      intro other member
      rcases List.mem_cons.mp member with same | later
      · subst other
        simp [dominates]
      · cases rest with
        | nil => simp at later
        | cons head tail =>
          simp [freshest] at missing
          split at missing <;> simp at missing
    next candidate found =>
      have maximal := induction candidate found
      split at selected
      next newer =>
        cases Option.some.inj selected
        intro other member
        rcases List.mem_cons.mp member with same | later
        · subst other
          simp only [earlier, dominates] at *
          omega
        · exact maximal other later
      next notNewer =>
        cases Option.some.inj selected
        intro other member
        rcases List.mem_cons.mp member with same | later
        · subst other
          simp [dominates]
        · have previous := maximal other later
          simp only [earlier, dominates] at *
          omega

def contemporaneous (first second : Extent) (tolerance : Nat) : Bool :=
  match first.time, second.time with
  | none, none => true
  | some first, some second => decide
      (first ≤ second + tolerance ∧ second ≤ first + tolerance)
  | _, _ => false

def disagrees (first second : Extent) (difference tolerance ratio symmetric : Nat) :
    Bool :=
  contemporaneous first second tolerance && decide (0 < first.area ∧
    (ratio * first.area < 100 * second.area ∨
      (first.area < second.area ∧ symmetric * first.area < 100 * difference)))

def extent (firis wfigs : List Extent) (difference : Nat → Nat → Nat)
    (tolerance ratio symmetric : Nat) : Bool :=
  match freshest firis, freshest wfigs with
  | some first, some second => disagrees first second
      (difference first.shape second.shape) tolerance ratio symmetric
  | _, _ => false

theorem disagreement_requires_contemporaneous_sources (first second : Extent)
    (difference tolerance ratio symmetric : Nat)
    (accepted : disagrees first second difference tolerance ratio symmetric = true) :
    contemporaneous first second tolerance = true := by
  simp only [disagrees, Bool.and_eq_true, decide_eq_true_eq] at accepted
  exact accepted.1

theorem disagreement_requires_larger_wfigs (first second : Extent)
    (difference tolerance ratio symmetric : Nat) (ratioFloor : 100 ≤ ratio)
    (accepted : disagrees first second difference tolerance ratio symmetric = true) :
    first.area < second.area := by
  simp only [disagrees, Bool.and_eq_true, decide_eq_true_eq] at accepted
  have condition := accepted.2
  rcases condition.2 with larger | larger
  · have bound := Nat.mul_le_mul_right first.area ratioFloor
    omega
  · exact larger.1

theorem missing_feed_cannot_disagree (values : List Extent)
    (difference : Nat → Nat → Nat) (tolerance ratio symmetric : Nat) :
    extent [] values difference tolerance ratio symmetric = false ∧
      extent values [] difference tolerance ratio symmetric = false := by
  simp [extent, freshest]

end PeriScribe.BorderClassification
