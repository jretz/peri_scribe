import Std

namespace PeriScribe.SparseEvidence

structure Perimeter where
  measured : Option Int
  supplied : Option Int
  deriving Repr

structure Report where
  size : Option Int
  discovery : Option Int
  final : Option Int
  deriving Repr

/-- Zero remains reporting evidence; only positive geometry is usable mapping. -/
def positive (value : Option Int) : Option Int := value.filter (0 < ·)
def nonnegative (value : Option Int) : Option Int := value.filter (0 ≤ ·)

def lastKnown : List (Option Int) → Option Int
  | [] => none
  | first :: rest => (lastKnown rest).or first

def maximum : List Int → Option Int
  | [] => none
  | first :: rest => match maximum rest with
    | none => some first
    | some previous => some (max first previous)

/-- Sparse current size checks only the final reporting row after usable geometry. -/
def latest (dated : List Int) (perimeters : List Perimeter)
    (points : List Report) : Option Int :=
  dated.getLast?.or ((lastKnown (perimeters.map (positive ∘ Perimeter.measured))).or
    ((points.getLast?.bind Report.size).or
      (perimeters.getLast?.bind Perimeter.supplied)))

/-- A measured perimeter masks that row's supplied area, even when supply is larger. -/
def fallback (perimeters : List Perimeter)
    (points incidents : List Report) : List Int :=
  perimeters.filterMap (fun row => (positive row.measured).or
    (nonnegative row.supplied)) ++
    (points ++ incidents).flatMap (fun row =>
      [nonnegative row.size, nonnegative row.discovery, nonnegative row.final]
        |>.filterMap id)

def historical (dated : List Int) (perimeters : List Perimeter)
    (points incidents : List Report) : Option Int :=
  if dated.isEmpty then maximum (fallback perimeters points incidents)
  else maximum dated

def visible (threshold : Int) (area : Option Int) : Bool :=
  area.any (threshold ≤ ·)

theorem maximum_is_evidence (values : List Int) (value : Int)
    (selected : maximum values = some value) : value ∈ values := by
  induction values generalizing value with
  | nil => simp [maximum] at selected
  | cons first rest induction =>
    simp only [maximum] at selected
    cases previous : maximum rest with
    | none => simp [previous] at selected; simp [← selected]
    | some prior =>
      simp only [previous, Option.some.injEq] at selected
      by_cases ordering : first ≤ prior
      · rw [Int.max_eq_right ordering] at selected
        subst value
        exact List.mem_cons_of_mem _ (induction prior previous)
      · rw [Int.max_eq_left (by omega)] at selected
        simp [← selected]

theorem maximum_bounds_evidence (values : List Int) (value : Int)
    (selected : maximum values = some value) : ∀ item ∈ values, item ≤ value := by
  induction values generalizing value with
  | nil => simp
  | cons first rest induction =>
    simp only [maximum] at selected
    cases previous : maximum rest with
    | none =>
      have empty : rest = [] := by
        cases rest with
        | nil => rfl
        | cons head tail =>
          simp only [maximum] at previous
          split at previous <;> contradiction
      subst rest
      have same : first = value := by simpa [previous] using selected
      simp [same]
    | some prior =>
      simp only [previous, Option.some.injEq] at selected
      intro item member
      rcases List.mem_cons.mp member with same | remaining
      · subst item; rw [← selected]; exact Int.le_max_left _ _
      · exact Int.le_trans (induction prior previous item remaining)
          (by rw [← selected]; exact Int.le_max_right _ _)

theorem maximum_exists (values : List Int) (item : Int) (member : item ∈ values) :
    ∃ value, maximum values = some value := by
  cases values with
  | nil => simp at member
  | cons first rest =>
    cases previous : maximum rest <;> simp [maximum, previous]

/-- Inclusion has an evidence witness rather than a fabricated default zero. -/
theorem visibility_has_witness (values : List Int) (threshold : Int) :
    visible threshold (maximum values) = true ↔
      ∃ value ∈ values, threshold ≤ value := by
  constructor
  · intro accepted
    cases selected : maximum values with
    | none => simp [visible, selected] at accepted
    | some value =>
      exact ⟨value, maximum_is_evidence values value selected,
        by simpa [visible, selected] using accepted⟩
  · rintro ⟨item, member, reaches⟩
    obtain ⟨value, selected⟩ := maximum_exists values item member
    have bound := maximum_bounds_evidence values value selected item member
    simp [visible, selected, Int.le_trans reaches bound]

theorem dated_latest_dominates_sparse (first : Int) (rest : List Int)
    (perimeters : List Perimeter) (points : List Report) :
    latest (first :: rest) perimeters points = (first :: rest).getLast? := by
  cases rest with
  | nil => simp [latest]
  | cons next tail =>
    simp only [latest]
    cases chosen : (first :: next :: tail).getLast? with
    | none => simp at chosen
    | some value => simp

theorem dated_history_dominates_sparse (first : Int) (rest : List Int)
    (perimeters : List Perimeter) (points incidents : List Report) :
    historical (first :: rest) perimeters points incidents =
      maximum (first :: rest) := by simp [historical]

theorem usable_geometry_precedes_reporting (perimeters : List Perimeter)
    (points : List Report) (area : Int)
    (selected : lastKnown (perimeters.map (positive ∘ Perimeter.measured)) =
      some area) : latest [] perimeters points = some area := by
  simp [latest, selected]

theorem last_point_can_supply_zero (before : List Report) :
    latest [] [] (before ++ [⟨some 0, none, none⟩]) = some 0 := by
  simp [latest, lastKnown]

theorem missing_last_point_does_not_reuse_older_size (before : List Report) :
    latest [] [] (before ++ [⟨none, none, none⟩]) = none := by
  simp [latest, lastKnown]

theorem zero_mapping_cannot_hide_supplied_size (area : Int) (valid : 0 ≤ area) :
    fallback [⟨some 0, some area⟩] [] [] = [area] := by
  simp [fallback, positive, nonnegative, List.filterMap, Option.filter, valid]

theorem sparse_visibility_has_actual_fallback_witness (perimeters : List Perimeter)
    (points incidents : List Report) (threshold : Int) :
    visible threshold (historical [] perimeters points incidents) = true ↔
      ∃ value ∈ fallback perimeters points incidents, threshold ≤ value := by
  simpa [historical] using
    visibility_has_witness (fallback perimeters points incidents) threshold

theorem dated_correction_keeps_historical_qualification (before after : List Int)
    (threshold : Int) (qualified : visible threshold (maximum before) = true) :
    visible threshold (maximum (before ++ after)) = true := by
  obtain ⟨value, member, reaches⟩ :=
    (visibility_has_witness before threshold).mp qualified
  exact (visibility_has_witness (before ++ after) threshold).mpr
    ⟨value, List.mem_append_left _ member, reaches⟩

theorem zero_is_not_missing :
    latest [] [] [⟨some 0, none, none⟩] = some 0 ∧ latest [] [] [] = none := by decide

/-- The first dated estimate deliberately supersedes unrelated undated fallback. -/
theorem first_date_can_remove_sparse_qualification :
    visible 25 (historical [] [⟨some 100, none⟩] [] []) = true ∧
    visible 25 (historical [1] [⟨some 100, none⟩] [] []) = false := by decide

end PeriScribe.SparseEvidence
