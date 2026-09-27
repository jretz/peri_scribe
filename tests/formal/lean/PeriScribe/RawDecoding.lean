import Std

namespace PeriScribe.RawDecoding

/- A value is classified by its requested type, before selecting a field. Numeric
   payloads represent finite values; text payloads represent nonblank stripped text.
   Lexing and Python's calendar implementation remain external assumptions. -/
inductive Candidate (α : Type) where
  | missing
  | boolean (value : Bool)
  | malformed
  | nonfinite
  | usable (value : α)
  deriving DecidableEq, Repr

def decode : Candidate α → Option α
  | .usable value => some value
  | _ => none

def first (parser : α → Option β) : List α → Option β
  | [] => none
  | value :: rest => match parser value with
    | some result => some result
    | none => first parser rest

theorem first_eq_successful_head (parser : α → Option β) (values : List α) :
    first parser values = (values.filterMap parser).head? := by
  induction values with
  | nil => rfl
  | cons value rest ih =>
    simp only [first, List.filterMap_cons]
    cases parser value <;> simp_all

theorem first_none_iff (parser : α → Option β) (values : List α) :
    first parser values = none ↔ ∀ value ∈ values, parser value = none := by
  induction values with
  | nil => simp [first]
  | cons value rest ih =>
    cases h : parser value <;> simp [first, h, ih]

theorem first_append (parser : α → Option β) (left right : List α) :
    first parser (left ++ right) =
      match first parser left with
      | some value => some value
      | none => first parser right := by
  induction left with
  | nil => rfl
  | cons value rest ih =>
    cases h : parser value <;> simp [first, h, ih]

theorem first_some_iff (parser : α → Option β) (values : List α) (result : β) :
    first parser values = some result ↔
      ∃ before value after, values = before ++ value :: after ∧
        (∀ skipped ∈ before, parser skipped = none) ∧ parser value = some result := by
  induction values with
  | nil => simp [first]
  | cons value rest ih =>
    constructor
    · intro found
      cases h : parser value with
      | some decoded =>
        have same : decoded = result := by simpa [first, h] using found
        exact ⟨[], value, rest, rfl, by simp, by simp [h, same]⟩
      | none =>
        obtain ⟨before, selected, after, eq, skipped, chosen⟩ :=
          ih.mp (by simpa [first, h] using found)
        exact ⟨value :: before, selected, after, by simp [eq],
          by
            intro item member
            rcases List.mem_cons.mp member with eq | old
            · simpa [eq] using h
            · exact skipped item old, chosen⟩
    · rintro ⟨before, selected, after, eq, skipped, chosen⟩
      rw [eq, first_append, (first_none_iff parser before).mpr skipped]
      simp [first, chosen]

theorem first_preserves_priority (parser : α → Option β) (left right : List α)
    (value : β) (found : first parser left = some value) :
    first parser (left ++ right) = some value := by
  simp [first_append, found]

theorem unusable_prefix_irrelevant (parser : α → Option β) (before values : List α)
    (unusable : ∀ value ∈ before, parser value = none) :
    first parser (before ++ values) = first parser values := by
  simp [first_append, (first_none_iff parser before).mpr unusable]

theorem first_result_from_input (parser : α → Option β) (values : List α) (result : β)
    (found : first parser values = some result) :
    ∃ value ∈ values, parser value = some result := by
  obtain ⟨before, value, after, eq, _, chosen⟩ :=
    (first_some_iff parser values result).mp found
  exact ⟨value, by simp [eq], chosen⟩

theorem zero_preserved (rest : List (Candidate Int)) :
    first decode (.usable 0 :: rest) = some 0 := rfl

theorem missing_does_not_mask (rest : List (Candidate α)) :
    first decode (.missing :: rest) = first decode rest := rfl

theorem malformed_does_not_mask (rest : List (Candidate α)) :
    first decode (.malformed :: rest) = first decode rest := rfl

theorem booleans_do_not_mask (value : Bool) (rest : List (Candidate α)) :
    first decode (.boolean value :: rest) = first decode rest := rfl

theorem nonfinite_does_not_mask (rest : List (Candidate α)) :
    first decode (.nonfinite :: rest) = first decode rest := rfl

/- Exact UTC microseconds from 1970, with Python datetime's representable bounds. -/
def minimum : Int := -62135596800000000
def maximum : Int := 253402300799999999

def bounded (instant : Int) : Option Int :=
  if minimum ≤ instant ∧ instant ≤ maximum then some instant else none

def normalize (wall offset : Int) : Option Int := bounded (wall - offset)

def milliseconds (value : Int) : Option Int := bounded (value * 1000)

theorem bounded_some_iff (instant result : Int) :
    bounded instant = some result ↔
      minimum ≤ instant ∧ instant ≤ maximum ∧ result = instant := by
  simp only [bounded]
  split <;> simp_all <;> omega

theorem bounded_none_iff (instant : Int) :
    bounded instant = none ↔ instant < minimum ∨ maximum < instant := by
  simp only [bounded]
  split <;> simp_all <;> omega

theorem normalized_in_range (wall offset result : Int)
    (success : normalize wall offset = some result) :
    minimum ≤ result ∧ result ≤ maximum := by
  obtain ⟨lo, hi, eq⟩ := (bounded_some_iff (wall - offset) result).mp success
  omega

theorem normalization_representation_invariant (wall offset delta : Int) :
    normalize (wall + delta) (offset + delta) = normalize wall offset := by
  unfold normalize
  congr 1
  omega

theorem utc_normalization_idempotent (wall offset result : Int)
    (success : normalize wall offset = some result) :
    normalize result 0 = some result := by
  have bounds := normalized_in_range wall offset result success
  simp [normalize, bounded, bounds]

theorem same_normalized_instant (a offsetA b offsetB result : Int)
    (first : normalize a offsetA = some result) :
    normalize b offsetB = some result ↔ a - offsetA = b - offsetB := by
  have known := (bounded_some_iff (a - offsetA) result).mp first
  simp only [normalize, bounded_some_iff]
  omega

theorem normalization_preserves_order (a b offset firstResult secondResult : Int)
    (first : normalize a offset = some firstResult)
    (second : normalize b offset = some secondResult) :
    firstResult ≤ secondResult ↔ a ≤ b := by
  have fst := (bounded_some_iff (a - offset) firstResult).mp first
  have snd := (bounded_some_iff (b - offset) secondResult).mp second
  omega

theorem milliseconds_agree_with_utc (value : Int) :
    milliseconds value = normalize (value * 1000) 0 := by
  simp [milliseconds, normalize]

theorem epoch_zero_preserved : milliseconds 0 = some 0 := by decide

end PeriScribe.RawDecoding
