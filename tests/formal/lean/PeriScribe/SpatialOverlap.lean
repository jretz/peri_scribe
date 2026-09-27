import Std

namespace PeriScribe.SpatialOverlap

/-- Closed rectangles include edge and corner touches in an intersection query. -/
structure Box where
  left : Int
  bottom : Int
  right : Int
  top : Int
  deriving Repr, DecidableEq

def intersects (first second : Box) : Bool :=
  decide (first.left ≤ second.right ∧ second.left ≤ first.right ∧
    first.bottom ≤ second.top ∧ second.bottom ≤ first.top)

def encloses (outer inner : Box) : Prop :=
  outer.left ≤ inner.left ∧ inner.right ≤ outer.right ∧
    outer.bottom ≤ inner.bottom ∧ inner.top ≤ outer.top

def combine (first second : Box) : Box :=
  ⟨min first.left second.left, min first.bottom second.bottom,
    max first.right second.right, max first.top second.top⟩

def envelope : List Box → Option Box
  | [] => none
  | first :: rest => match envelope rest with
    | none => some first
    | some remaining => some (combine first remaining)

theorem combined_encloses_left (first second : Box) :
    encloses (combine first second) first := by
  simp only [encloses, combine]
  omega

theorem combined_encloses_right (first second : Box) :
    encloses (combine first second) second := by
  simp only [encloses, combine]
  omega

theorem enclosure_transitive (first second third : Box)
    (one : encloses first second) (two : encloses second third) :
    encloses first third := by simp only [encloses] at *; omega

theorem empty_envelope_iff (parts : List Box) : envelope parts = none ↔ parts = [] := by
  cases parts with
  | nil => simp [envelope]
  | cons first rest => simp only [envelope]; split <;> simp

theorem envelope_encloses_every_part (parts : List Box) (bounds part : Box)
    (computed : envelope parts = some bounds) (member : part ∈ parts) :
    encloses bounds part := by
  induction parts generalizing bounds with
  | nil => simp at member
  | cons first rest induction =>
    simp only [envelope] at computed
    split at computed
    next missing =>
      cases Option.some.inj computed
      have empty := (empty_envelope_iff rest).mp missing
      subst rest
      simp only [List.mem_singleton] at member
      subst part
      simp [encloses]
    next remaining found =>
      cases Option.some.inj computed
      rcases List.mem_cons.mp member with same | later
      · subst part
        exact combined_encloses_left first remaining
      · exact enclosure_transitive _ _ _ (combined_encloses_right first remaining)
          (induction remaining found later)

theorem intersections_survive_enclosures (first second outerFirst outerSecond : Box)
    (one : encloses outerFirst first) (two : encloses outerSecond second)
    (hit : intersects first second = true) :
    intersects outerFirst outerSecond = true := by
  simp only [encloses, intersects, decide_eq_true_eq] at *
  omega

abbrev Shape := List Box

def overlap (first second : Shape) : Bool :=
  first.any (fun part => second.any (intersects part))

def candidate (first second : Shape) : Bool :=
  match envelope first, envelope second with
  | some left, some right => intersects left right
  | _, _ => false

theorem exact_overlap_has_candidate (first second : Shape)
    (hit : overlap first second = true) : candidate first second = true := by
  obtain ⟨part, present, other, included, overlap⟩ := by
    simpa [overlap] using hit
  cases firstBounds : envelope first with
  | none =>
    have empty := (empty_envelope_iff first).mp firstBounds
    simp [empty] at present
  | some firstBox =>
    cases secondBounds : envelope second with
    | none =>
      have empty := (empty_envelope_iff second).mp secondBounds
      simp [empty] at included
    | some secondBox =>
      simp only [candidate, firstBounds, secondBounds]
      exact intersections_survive_enclosures part other firstBox secondBox
        (envelope_encloses_every_part first firstBox part firstBounds present)
        (envelope_encloses_every_part second secondBox other secondBounds included)
        overlap

structure Query where
  identity : Nat
  shape : Shape
  deriving Repr

def candidates (queries : List Query) (features : List Shape) : List Shape :=
  features.filter (fun feature =>
    queries.any (fun query => candidate query.shape feature))

def matchingIndices (queries : List Query) (features : List Shape) : List Nat :=
  ((queries.filter (fun query => features.any (overlap query.shape))).map
    Query.identity).eraseDups

def indexed (queries : List Query) (features : List Shape) : List Nat :=
  matchingIndices queries (candidates queries features)

theorem match_has_original_query_and_feature (queries : List Query)
    (features : List Shape) (identity : Nat) :
    identity ∈ matchingIndices queries features ↔
      ∃ query ∈ queries, query.identity = identity ∧
        ∃ feature ∈ features, overlap query.shape feature = true := by
  simp [matchingIndices, and_left_comm, and_comm]

theorem indexed_equals_exhaustive_membership (queries : List Query)
    (features : List Shape) (identity : Nat) :
    identity ∈ indexed queries features ↔
      identity ∈ matchingIndices queries features := by
  simp only [indexed, match_has_original_query_and_feature]
  constructor
  · rintro ⟨query, included, same, feature, selected, hit⟩
    exact ⟨query, included, same, feature, (List.mem_filter.mp selected).1, hit⟩
  · rintro ⟨query, included, same, feature, present, hit⟩
    refine ⟨query, included, same, feature, ?_, hit⟩
    apply List.mem_filter.mpr
    exact ⟨present, List.any_eq_true.mpr
      ⟨query, included, exact_overlap_has_candidate query.shape feature hit⟩⟩

theorem streaming_batches_equal_exhaustive (queries : List Query)
    (chunks : List (List Shape)) (identity : Nat) :
    identity ∈ (chunks.flatMap (matchingIndices queries)).eraseDups ↔
      identity ∈ matchingIndices queries chunks.flatten := by
  simp only [List.mem_eraseDups, List.mem_flatMap,
    match_has_original_query_and_feature, List.mem_flatten]
  constructor
  · rintro ⟨chunk, contained, query, included, same, feature, present, hit⟩
    exact ⟨query, included, same, feature, ⟨chunk, contained, present⟩, hit⟩
  · rintro ⟨query, included, same, feature, ⟨chunk, contained, present⟩, hit⟩
    exact ⟨chunk, contained, query, included, same, feature, present, hit⟩

theorem empty_queries_never_match (features : List Shape) :
    matchingIndices [] features = [] := by simp [matchingIndices]

theorem query_without_geometry_cannot_match (identity : Nat) (features : List Shape) :
    matchingIndices [⟨identity, []⟩] features = [] := by simp [matchingIndices, overlap]

theorem coincident_queries_keep_their_own_identity (first second : Nat) (shape : Shape)
    (features : List Shape) (hit : ∃ feature ∈ features, overlap shape feature = true) :
    first ∈ matchingIndices [⟨first, shape⟩, ⟨second, shape⟩] features ∧
      second ∈ matchingIndices [⟨first, shape⟩, ⟨second, shape⟩] features := by
  simp only [match_has_original_query_and_feature]
  exact ⟨⟨⟨first, shape⟩, by simp, rfl, hit⟩,
    ⟨⟨second, shape⟩, by simp, rfl, hit⟩⟩

end PeriScribe.SpatialOverlap
