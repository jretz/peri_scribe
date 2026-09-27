import Std

namespace PeriScribe.Geography

/-- Predicates represent ideal footprints, independent of GEOS and coordinate units. -/
abbrev Footprint (Point : Type) := Point → Prop

/-- The empty suffix represents the universal set, the identity of intersection. -/
def suffixIntersection {Point : Type} : List (Footprint Point) → Footprint Point
  | [] => fun _ => True
  | footprint :: rest => fun point => footprint point ∧ suffixIntersection rest point

/-- Each earlier observation is corrected by every later observation. -/
def corrected {Point : Type} : List (Footprint Point) → List (Footprint Point)
  | [] => []
  | footprint :: rest =>
    (fun point => footprint point ∧ suffixIntersection rest point) :: corrected rest

/-- Each observation intersects the already corrected successor. -/
def reverseIntersections {Point : Type} :
    List (Footprint Point) → List (Footprint Point)
  | [] => []
  | footprint :: rest =>
    match reverseIntersections rest with
    | [] => [footprint]
    | later :: remaining =>
      (fun point => footprint point ∧ later point) :: later :: remaining

/-- Concrete representations share the reverse recurrence through intersection. -/
def reverseCombine {Value : Type} (combine : Value → Value → Value) :
    List Value → List Value
  | [] => []
  | value :: rest =>
    match reverseCombine combine rest with
    | [] => [value]
    | later :: remaining => combine value later :: later :: remaining

theorem concrete_recurrence_refines_set_recurrence {Value Point : Type}
    (combine : Value → Value → Value) (encode : Value → Footprint Point)
    (intersection : ∀ left right,
      encode (combine left right) = fun point => encode left point ∧ encode right point)
    (history : List Value) :
    (reverseCombine combine history).map encode =
      reverseIntersections (history.map encode) := by
  induction history with
  | nil => rfl
  | cons first rest induction =>
    rw [reverseCombine, List.map_cons, reverseIntersections, ← induction]
    cases reverseCombine combine rest with
    | nil => rfl
    | cons later remaining =>
      simp only [List.map_cons, intersection]

/-- Boolean membership makes finite-cell conformance executable. -/
def booleanCorrected {Point : Type} (history : List (Point → Bool)) :
    List (Point → Bool) :=
  reverseCombine (fun left right point => left point && right point) history

theorem boolean_recurrence_matches_ideal_sets {Point : Type}
    (history : List (Point → Bool)) :
    (booleanCorrected history).map (fun footprint point => footprint point = true) =
      reverseIntersections
        (history.map (fun footprint point => footprint point = true)) := by
  apply concrete_recurrence_refines_set_recurrence
  intro left right
  funext point
  exact propext (by simp)

theorem reverse_recurrence_matches_all_later_intersections {Point : Type}
    (history : List (Footprint Point)) :
    reverseIntersections history = corrected history := by
  induction history with
  | nil => rfl
  | cons first rest induction =>
    cases rest with
    | nil =>
      simp only [reverseIntersections, corrected]
      congr 1
      funext point
      exact propext (by simp [suffixIntersection])
    | cons next tail =>
      rw [reverseIntersections, induction]
      rfl

theorem corrected_length {Point : Type} (history : List (Footprint Point)) :
    (corrected history).length = history.length := by
  induction history with
  | nil => rfl
  | cons first rest induction => simp [corrected, induction]

theorem suffix_intersection_is_all_later {Point : Type}
    (history : List (Footprint Point)) (point : Point) :
    suffixIntersection history point ↔ ∀ footprint ∈ history, footprint point := by
  induction history with
  | nil => simp [suffixIntersection]
  | cons first rest induction => simp [suffixIntersection, induction]

theorem corrected_first_never_exceeds_later {Point : Type}
    (first later : Footprint Point) (rest : List (Footprint Point)) (point : Point)
    (inside : suffixIntersection (first :: rest) point) (present : later ∈ rest) :
    later point := by
  exact (suffix_intersection_is_all_later rest point).mp inside.2 later present

/-- A ring contains exactly the points first added at a corrected growth step. -/
def ring {Point : Type} (previous current : Footprint Point) : Footprint Point :=
  fun point => current point ∧ ¬ previous point

theorem growth_ring_does_not_overlap_previous {Point : Type}
    (previous current : Footprint Point) (point : Point) :
    ¬ (ring previous current point ∧ previous point) := by
  intro overlap
  exact overlap.1.2 overlap.2

theorem growth_ring_reconstructs_nested_footprint {Point : Type}
    (previous current : Footprint Point)
    (nested : ∀ point, previous point → current point)
    (point : Point) :
    (previous point ∨ ring previous current point) ↔ current point := by
  constructor
  · intro inside
    exact inside.elim (nested point) And.left
  · intro inside
    by_cases old : previous point
    · exact Or.inl old
    · exact Or.inr ⟨inside, old⟩

theorem successive_rings_are_disjoint {Point : Type}
    (earlierPrevious earlier previous current : Footprint Point)
    (nested : ∀ point, earlier point → previous point) (point : Point) :
    ¬ (ring earlierPrevious earlier point ∧ ring previous current point) := by
  intro overlap
  exact overlap.2.2 (nested point overlap.1.1)

/-- Corrected footprints can only grow after shrinkage propagates backwards. -/
def Nested {Point : Type} (previous : Footprint Point) : List (Footprint Point) → Prop
  | [] => True
  | current :: rest => (∀ point, previous point → current point) ∧ Nested current rest

/-- Rings start from an explicit baseline, normally the empty set. -/
def rings {Point : Type} (previous : Footprint Point) :
    List (Footprint Point) → List (Footprint Point)
  | [] => []
  | current :: rest => ring previous current :: rings current rest

/-- Carrying a baseline makes the empty-history case total. -/
def finalFootprint {Point : Type} (previous : Footprint Point) :
    List (Footprint Point) → Footprint Point
  | [] => previous
  | current :: rest => finalFootprint current rest

theorem corrected_nested_from_baseline {Point : Type}
    (history : List (Footprint Point)) (previous : Footprint Point)
    (contained : ∀ point, previous point → suffixIntersection history point) :
    Nested previous (corrected history) := by
  induction history generalizing previous with
  | nil => trivial
  | cons first rest induction =>
    refine ⟨contained, ?_⟩
    exact induction _ (fun _ inside => inside.2)

theorem corrected_footprints_are_nested {Point : Type}
    (history : List (Footprint Point)) :
    Nested (fun _ => False) (corrected history) := by
  exact corrected_nested_from_baseline history _ (fun _ impossible => impossible.elim)

theorem correction_preserves_final_observation {Point : Type}
    (history : List (Footprint Point)) (previous : Footprint Point) :
    finalFootprint previous (corrected history) = finalFootprint previous history := by
  induction history generalizing previous with
  | nil => rfl
  | cons first rest induction =>
    cases rest with
    | nil =>
      funext point
      exact propext (by simp [corrected, finalFootprint, suffixIntersection])
    | cons next tail =>
      simpa only [corrected, finalFootprint] using induction previous

theorem ring_union_reconstructs_final_footprint {Point : Type}
    (history : List (Footprint Point)) (previous : Footprint Point)
    (nested : Nested previous history) (point : Point) :
    (previous point ∨ ∃ boundary ∈ rings previous history, boundary point) ↔
      finalFootprint previous history point := by
  induction history generalizing previous with
  | nil => simp [rings, finalFootprint]
  | cons current rest induction =>
    have step := growth_ring_reconstructs_nested_footprint
      previous current nested.1 point
    have later := induction current nested.2
    simp only [rings, List.mem_cons, exists_eq_or_imp, finalFootprint]
    rw [← later, ← step]
    exact or_assoc.symm

theorem rings_avoid_baseline {Point : Type}
    (history : List (Footprint Point)) (previous : Footprint Point)
    (nested : Nested previous history) (point : Point)
    (boundary : Footprint Point) (present : boundary ∈ rings previous history)
    (inside : boundary point) : ¬ previous point := by
  induction history generalizing previous with
  | nil => simp [rings] at present
  | cons current rest induction =>
    simp only [rings, List.mem_cons] at present
    rcases present with first | later
    · subst boundary
      exact inside.2
    · intro old
      exact induction current nested.2 later (nested.1 point old)

theorem rings_form_pairwise_disjoint_partition {Point : Type}
    (history : List (Footprint Point)) (previous : Footprint Point)
    (nested : Nested previous history) :
    (rings previous history).Pairwise
      (fun left right => ∀ point, ¬ (left point ∧ right point)) := by
  induction history generalizing previous with
  | nil => simp [rings]
  | cons current rest induction =>
    apply List.pairwise_cons.mpr
    constructor
    · intro later present point overlap
      exact rings_avoid_baseline rest current nested.2 point later present
        overlap.2 overlap.1.1
    · exact induction current nested.2

theorem corrected_rings_cover_final_footprint {Point : Type}
    (history : List (Footprint Point)) (point : Point) :
    (∃ boundary ∈ rings (fun _ => False) (corrected history), boundary point) ↔
      finalFootprint (fun _ => False) history point := by
  simpa [correction_preserves_final_observation] using
    ring_union_reconstructs_final_footprint (corrected history)
    (fun _ => False) (corrected_footprints_are_nested history) point

/-- Identity/proximity edges are assumed symmetric; reachability defines membership. -/
inductive Connected {Record : Type} (edge : Record → Record → Prop) :
    Record → Record → Prop where
  | same (record : Record) : Connected edge record record
  | step {first next last : Record} :
    edge first next → Connected edge next last → Connected edge first last

theorem connected_transitive {Record : Type} {edge : Record → Record → Prop}
    {first middle last : Record} (left : Connected edge first middle)
    (right : Connected edge middle last) : Connected edge first last := by
  induction left with
  | same => exact right
  | step adjacent _ induction => exact Connected.step adjacent (induction right)

theorem connected_symmetric {Record : Type} {edge : Record → Record → Prop}
    (symmetric : ∀ first second, edge first second → edge second first)
    {first last : Record} (connected : Connected edge first last) :
    Connected edge last first := by
  induction connected with
  | same => exact Connected.same _
  | step adjacent _ induction =>
    exact connected_transitive induction
      (Connected.step (symmetric _ _ adjacent) (Connected.same _))

theorem components_coincide_if_they_overlap {Record : Type}
    {edge : Record → Record → Prop}
    (symmetric : ∀ first second, edge first second → edge second first)
    {first second shared : Record}
    (left : Connected edge first shared) (right : Connected edge second shared)
    (record : Record) :
    Connected edge first record ↔ Connected edge second record := by
  constructor
  · intro member
    exact connected_transitive right
      (connected_transitive (connected_symmetric symmetric left) member)
  · intro member
    exact connected_transitive left
      (connected_transitive (connected_symmetric symmetric right) member)

end PeriScribe.Geography
