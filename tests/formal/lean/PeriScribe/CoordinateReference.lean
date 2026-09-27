import Std

namespace PeriScribe.CoordinateReference

/-- Common positive scaling represents finite binary coordinates exactly as integers. -/
def magnitude (value : Int) : Int := if value < 0 then -value else value

def axisFits (low high minimum maximum : Int) : Bool :=
  decide (max (magnitude low) (magnitude high) ≤ maximum ∧
    ¬(0 < minimum ∧ low ≤ 0 ∧ 0 ≤ high) ∧
    minimum ≤ min (magnitude low) (magnitude high))

theorem magnitude_nonnegative (value : Int) : 0 ≤ magnitude value := by
  unfold magnitude; split <;> omega

theorem axis_fits_iff_every_coordinate (low high minimum maximum : Int)
    (ordered : low ≤ high) (nonnegative : 0 ≤ minimum) :
    axisFits low high minimum maximum = true ↔
      ∀ value, low ≤ value → value ≤ high →
        minimum ≤ magnitude value ∧ magnitude value ≤ maximum := by
  simp only [axisFits, decide_eq_true_eq]
  constructor
  · intro fits value lower upper
    unfold magnitude at *
    split <;> split at fits <;> split at fits <;> omega
  · intro fits
    have left := fits low (by omega) (by omega)
    have right := fits high (by omega) (by omega)
    have cannotCross : ¬(0 < minimum ∧ low ≤ 0 ∧ 0 ≤ high) := by
      intro crossing
      have zero := fits 0 crossing.2.1 crossing.2.2
      simp [magnitude] at zero
      omega
    omega

def longitudesFit (west east low high : Int) : Bool :=
  if west ≤ east then decide (west ≤ low ∧ high ≤ east)
  else decide (high ≤ east ∨ west ≤ low)

def longitudeAllowed (west east value : Int) : Prop :=
  if west ≤ east then west ≤ value ∧ value ≤ east
  else value ≤ east ∨ west ≤ value

theorem longitude_extent_is_sound (west east low high : Int)
    (fits : longitudesFit west east low high = true) :
    ∀ value, low ≤ value → value ≤ high → longitudeAllowed west east value := by
  intro value lower upper
  unfold longitudesFit at fits
  unfold longitudeAllowed
  split at fits <;> split <;> simp_all <;> omega

theorem ordinary_longitude_extent_is_exact (west east low high : Int)
    (ordinary : west ≤ east) (ordered : low ≤ high) :
    longitudesFit west east low high = true ↔
      ∀ value, low ≤ value → value ≤ high → longitudeAllowed west east value := by
  constructor
  · exact longitude_extent_is_sound west east low high
  · intro allowed
    have left := allowed low (by omega) (by omega)
    have right := allowed high (by omega) (by omega)
    simp only [longitudeAllowed, ordinary, ↓reduceIte] at left right
    simp [longitudesFit, ordinary, left.1, right.2]

inductive Kind where
  | excluded | outside | matching
  deriving DecidableEq, BEq, Repr

def classify (known domain geographic area : Bool) : Kind :=
  if !known || !domain then .excluded
  else if geographic && !area then .outside else .matching

theorem excluded_exact (known domain geographic area : Bool) :
    classify known domain geographic area = .excluded ↔
      known = false ∨ domain = false := by
  cases known <;> cases domain <;> cases geographic <;> cases area <;> decide

theorem matching_exact (known domain geographic area : Bool) :
    classify known domain geographic area = .matching ↔
      known = true ∧ domain = true ∧ (geographic = false ∨ area = true) := by
  cases known <;> cases domain <;> cases geographic <;> cases area <;> decide

theorem outside_exact (known domain geographic area : Bool) :
    classify known domain geographic area = .outside ↔
      known = true ∧ domain = true ∧ geographic = true ∧ area = false := by
  cases known <;> cases domain <;> cases geographic <;> cases area <;> decide

structure Candidate where
  key : Nat
  kind : Kind
  deriving DecidableEq, BEq, Repr

def singleton : List Nat → Option Nat
  | [key] => some key
  | _ => none

def keysOf (kind : Kind) (candidates : List Candidate) : List Nat :=
  (candidates.filter (fun candidate => decide (candidate.kind = kind))).map
      Candidate.key

/-- A unique in-area candidate has priority over the sole out-of-area fallback. -/
def select (hasGeometry : Bool) (candidates : List Candidate) : Option Nat :=
  if !hasGeometry then singleton (candidates.map Candidate.key)
  else match keysOf .matching candidates with
  | [] => singleton (keysOf .outside candidates)
  | foundKeys => singleton foundKeys

theorem singleton_exact (keys : List Nat) (key : Nat) :
    singleton keys = some key ↔ keys = [key] := by
  cases keys with
  | nil => simp [singleton]
  | cons first rest => cases rest <;> simp [singleton]

theorem singleton_permutation (first second : List Nat) (same : first.Perm second) :
    singleton first = singleton second := by
  cases found : singleton first with
  | none =>
    cases other : singleton second with
    | none => rfl
    | some key =>
      have secondOne := (singleton_exact second key).mp other
      have firstOne : first = [key] := by simpa [secondOne] using same
      simp [firstOne, singleton] at found
  | some key =>
    have firstOne := (singleton_exact first key).mp found
    have secondOne : second = [key] := by simpa [firstOne] using same.symm
    simp [secondOne, singleton]

theorem keys_of_permutation (kind : Kind) (first second : List Candidate)
    (same : first.Perm second) : (keysOf kind first).Perm (keysOf kind second) :=
  (same.filter _).map _

theorem selection_ignores_candidate_order (hasGeometry : Bool)
    (first second : List Candidate) (same : first.Perm second) :
    select hasGeometry first = select hasGeometry second := by
  have matching := keys_of_permutation .matching first second same
  have outside := keys_of_permutation .outside first second same
  unfold select
  split
  · exact singleton_permutation _ _ (same.map _)
  · cases firstMatches : keysOf .matching first with
    | nil =>
      have secondMatches : keysOf .matching second = [] := by
        simpa [firstMatches] using matching.symm
      simp only [secondMatches]
      exact singleton_permutation _ _ outside
    | cons key rest =>
      cases secondMatches : keysOf .matching second with
      | nil => simp [firstMatches, secondMatches] at matching
      | cons other tail =>
        exact singleton_permutation _ _ (by simpa [firstMatches, secondMatches]
          using matching)

theorem geometry_free_selection_exact (candidates : List Candidate) (key : Nat) :
    select false candidates = some key ↔ candidates.map Candidate.key = [key] := by
  exact singleton_exact _ _

theorem selected_matches_are_unique (candidates : List Candidate)
    (nonempty : keysOf .matching candidates ≠ []) (key : Nat) :
    select true candidates = some key ↔ keysOf .matching candidates = [key] := by
  simp only [select, Bool.not_true, Bool.false_eq_true, ↓reduceIte]
  exact singleton_exact _ _

theorem fallback_requires_no_matching (candidates : List Candidate)
    (noneMatch : keysOf .matching candidates = []) (key : Nat) :
    select true candidates = some key ↔ keysOf .outside candidates = [key] := by
  simpa [select, noneMatch] using singleton_exact (keysOf .outside candidates) key

theorem keys_of_have_source (kind : Kind) (candidates : List Candidate) (key : Nat)
    (member : key ∈ keysOf kind candidates) :
    ∃ candidate ∈ candidates, candidate.key = key ∧ candidate.kind = kind := by
  obtain ⟨candidate, present, same⟩ := List.mem_map.mp member
  obtain ⟨present, valid⟩ := List.mem_filter.mp present
  exact ⟨candidate, present, same, by simpa using valid⟩

theorem selection_never_invents_reference (hasGeometry : Bool)
    (candidates : List Candidate) (key : Nat)
    (selected : select hasGeometry candidates = some key) :
    key ∈ candidates.map Candidate.key := by
  unfold select at selected
  split at selected
  · simp [(singleton_exact _ _).mp selected]
  · split at selected
    · have one := (singleton_exact _ _).mp selected
      obtain ⟨candidate, member, same, _⟩ := keys_of_have_source .outside candidates key
        (by simp [one])
      exact List.mem_map.mpr ⟨candidate, member, same⟩
    · have one := (singleton_exact _ _).mp selected
      obtain ⟨candidate, member, same, _⟩ := keys_of_have_source .matching candidates
          key
        (by simp_all)
      exact List.mem_map.mpr ⟨candidate, member, same⟩

end PeriScribe.CoordinateReference
