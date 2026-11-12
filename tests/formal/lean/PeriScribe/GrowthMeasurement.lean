import Std

namespace PeriScribe.GrowthMeasurement

/-- Contributions belong to polygon surfaces; closing a line does not create one. -/
inductive Geometry where
  | polygon (contribution : Nat)
  | nonpolygon (closedCoordinateContribution : Int)
  | collection (left right : Geometry)
  deriving Repr

/-- A binary collection retains an arbitrary nested order of polygon additions. -/
def polygonArea : Geometry → Nat
  | .polygon contribution => contribution
  | .nonpolygon _ => 0
  | .collection left right => polygonArea left + polygonArea right

def polygonContributions : Geometry → List Nat
  | .polygon contribution => [contribution]
  | .nonpolygon _ => []
  | .collection left right => polygonContributions left ++ polygonContributions right

theorem filtering_keeps_all_polygon_contributions (geometry : Geometry) :
    polygonArea geometry = (polygonContributions geometry).sum := by
  induction geometry with
  | polygon contribution => simp [polygonArea, polygonContributions]
  | nonpolygon contribution => rfl
  | collection left right leftInduction rightInduction =>
    simp [polygonArea, polygonContributions, leftInduction, rightInduction]

def replaceNonpolygon (replace : Int → Int) : Geometry → Geometry
  | .polygon contribution => .polygon contribution
  | .nonpolygon contribution => .nonpolygon (replace contribution)
  | .collection left right =>
    .collection (replaceNonpolygon replace left) (replaceNonpolygon replace right)

theorem line_coordinate_contributions_cannot_change_area
    (replace : Int → Int) (geometry : Geometry) :
    polygonArea (replaceNonpolygon replace geometry) = polygonArea geometry := by
  induction geometry with
  | polygon contribution => rfl
  | nonpolygon contribution => rfl
  | collection left right leftInduction rightInduction =>
    simp [replaceNonpolygon, polygonArea, leftInduction, rightInduction]

/-- Positive surface weights provide an additive measure over exact finite cells. -/
abbrev Footprint := Nat → Bool

def union (left right : Footprint) : Footprint :=
  fun cell => left cell || right cell

def surfaceArea (cells : List Nat) (weight : Nat → Nat)
    (footprint : Footprint) : Nat :=
  match cells with
  | [] => 0
  | cell :: rest =>
    (if footprint cell then weight cell else 0) + surfaceArea rest weight footprint

theorem union_cannot_reduce_surface_area (cells : List Nat) (weight : Nat → Nat)
    (previous current : Footprint) :
    surfaceArea cells weight previous ≤
      surfaceArea cells weight (union previous current) := by
  induction cells with
  | nil => simp [surfaceArea]
  | cons cell rest induction =>
    cases before : previous cell <;> cases now : current cell <;>
      simp_all [surfaceArea, union] <;> omega

theorem revisiting_covered_ground_preserves_surface_area
    (cells : List Nat) (weight : Nat → Nat) (footprint : Footprint) :
    surfaceArea cells weight (union footprint footprint) =
      surfaceArea cells weight footprint := by
  have same : union footprint footprint = footprint := by
    funext cell
    simp [union]
  rw [same]

/-- Carry the complete cumulative footprint, including previously covered ground. -/
def addedAreas (cells : List Nat) (weight : Nat → Nat) (previous : Footprint) :
    List Footprint → List Nat
  | [] => []
  | current :: rest =>
    let combined := union previous current
    (surfaceArea cells weight combined - surfaceArea cells weight previous) ::
      addedAreas cells weight combined rest

def finalFootprint (previous : Footprint) : List Footprint → Footprint
  | [] => previous
  | current :: rest => finalFootprint (union previous current) rest

theorem covered_ground_adds_zero (cells : List Nat) (weight : Nat → Nat)
    (previous current : Footprint)
    (covered : ∀ cell, current cell = true → previous cell = true) :
    addedAreas cells weight previous [current] = [0] := by
  have same : union previous current = previous := by
    funext cell
    cases before : previous cell <;> cases now : current cell <;>
      simp_all [union]
  simp [addedAreas, same]

theorem cumulative_changes_telescope (cells : List Nat) (weight : Nat → Nat)
    (previous : Footprint) (history : List Footprint) :
    (addedAreas cells weight previous history).sum +
      surfaceArea cells weight previous =
      surfaceArea cells weight (finalFootprint previous history) := by
  induction history generalizing previous with
  | nil => simp [addedAreas, finalFootprint]
  | cons current rest induction =>
    simp only [addedAreas, List.sum_cons, finalFootprint]
    have monotone := union_cannot_reduce_surface_area cells weight previous current
    have remaining := induction (union previous current)
    omega

theorem empty_baseline_counts_final_coverage_once
    (cells : List Nat) (weight : Nat → Nat) (history : List Footprint) :
    (addedAreas cells weight (fun _ => false) history).sum =
      surfaceArea cells weight (finalFootprint (fun _ => false) history) := by
  have empty : surfaceArea cells weight (fun _ => false) = 0 := by
    induction cells with
    | nil => rfl
    | cons cell rest induction => simp [surfaceArea, induction]
  simpa [empty] using cumulative_changes_telescope cells weight (fun _ => false) history

/-- Repeat each edge's starting offset for the number of pieces it owns. -/
def pieceStarts (offset : Nat) : List Nat → List Nat
  | [] => []
  | count :: rest => List.replicate count offset ++ pieceStarts (offset + count) rest

private theorem consecutive_offsets_subtract_start (offset count : Nat) :
    List.zipWith Nat.sub (List.range' offset count) (List.replicate count offset) =
      List.range count := by
  apply List.ext_getElem
  · simp
  · intro index left right
    simp [List.getElem_range', List.getElem_zipWith]

/-- Subtracting repeated starts from flattened indices keeps each edge's local order. -/
theorem piece_ordinals_match_local_ranges (offset : Nat) (counts : List Nat) :
    List.zipWith Nat.sub (List.range' offset counts.sum) (pieceStarts offset counts) =
      counts.flatMap List.range := by
  induction counts generalizing offset with
  | nil => simp [pieceStarts]
  | cons count rest induction =>
    have consecutive :
        List.range' offset (count + rest.sum) =
          List.range' offset count ++ List.range' (offset + count) rest.sum := by
      have appended :=
        (List.range'_append (s := offset) (m := count) (n := rest.sum) (step := 1)).symm
      rwa [Nat.one_mul] at appended
    simp only [List.sum_cons, consecutive, pieceStarts, List.flatMap_cons]
    rw [List.zipWith_append (by simp), consecutive_offsets_subtract_start, induction]

end PeriScribe.GrowthMeasurement
