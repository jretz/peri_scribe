import Std

namespace PeriScribe.GeometryPreparation

/-- A digest selects a shard; the exact payload remains the equality authority. -/
def shard (count digest : Nat) : Nat := digest % count

def partition (count index : Nat) (entries : List (Nat × Nat)) : List (Nat × Nat) :=
  entries.filter (fun entry => shard count entry.1 == index)

theorem shard_membership_is_exact (count index : Nat) (entries : List (Nat × Nat))
    (entry : Nat × Nat) :
    entry ∈ partition count index entries ↔
      entry ∈ entries ∧ shard count entry.1 = index := by
  simp [partition]

theorem every_entry_has_one_shard (count : Nat) (entries : List (Nat × Nat))
    (entry : Nat × Nat) (present : entry ∈ entries) :
    entry ∈ partition count (shard count entry.1) entries := by
  simp [partition, present]

theorem distinct_shards_do_not_share_entries (count first second : Nat)
    (entries : List (Nat × Nat)) (different : first ≠ second)
    (entry : Nat × Nat) (present : entry ∈ partition count first entries) :
    entry ∉ partition count second entries := by
  simp only [shard_membership_is_exact] at present ⊢
  intro other
  exact different (present.2.symm.trans other.2)

/-- Exact byte classes retain their first occurrence position despite hash collisions. -/
def encodingClasses (history : List Nat) : List Nat := history.eraseDups

def encodingPosition (history : List Nat) (payload : Nat) : Nat :=
  (encodingClasses history).idxOf payload

theorem encoding_positions_are_exact (history : List Nat) (first second : Nat)
    (one : first ∈ history) (two : second ∈ history) :
    encodingPosition history first = encodingPosition history second ↔ first = second := by
  constructor
  · intro same
    have firstBound := List.idxOf_lt_length_of_mem
      (show first ∈ encodingClasses history by simpa [encodingClasses] using one)
    have secondBound := List.idxOf_lt_length_of_mem
      (show second ∈ encodingClasses history by simpa [encodingClasses] using two)
    have firstValue := List.getElem_idxOf firstBound
    have secondValue := List.getElem_idxOf secondBound
    simp only [encodingPosition] at same
    have rewritten : (encodingClasses history)[(encodingClasses history).idxOf second] =
        first := by simpa only [same] using firstValue
    exact rewritten.symm.trans secondValue
  · intro same
    rw [same]

def addEncoding (classes : List Nat) (payload : Nat) : List Nat :=
  if payload ∈ classes then classes else classes ++ [payload]

theorem adding_encoding_preserves_old_positions (classes : List Nat)
    (old fresh : Nat) (present : old ∈ classes) :
    (addEncoding classes fresh).idxOf old = classes.idxOf old := by
  simp only [addEncoding]
  split
  · rfl
  · simp [List.idxOf_append, present]

abbrev ProjectionKey := Nat × Nat
abbrev ProjectionMemo := ProjectionKey → Option Nat

def consistent (transform : ProjectionKey → Nat) (memo : ProjectionMemo) : Prop :=
  ∀ key value, memo key = some value → value = transform key

def projected (transform : ProjectionKey → Nat) (memo : ProjectionMemo)
    (key : ProjectionKey) : Nat := (memo key).getD (transform key)

def retain (memo : ProjectionMemo) (key : ProjectionKey) (value : Nat) : ProjectionMemo :=
  fun query => if query = key then some value else memo query

theorem projection_memo_preserves_transform (transform : ProjectionKey → Nat)
    (memo : ProjectionMemo) (valid : consistent transform memo) (key : ProjectionKey) :
    projected transform memo key = transform key := by
  cases found : memo key with
  | none => simp [projected, found]
  | some value => simpa [projected, found] using valid key value found

theorem retaining_projection_preserves_consistency (transform : ProjectionKey → Nat)
    (memo : ProjectionMemo) (valid : consistent transform memo) (key : ProjectionKey) :
    consistent transform (retain memo key (transform key)) := by
  intro query value found
  simp only [retain] at found
  split at found
  next same =>
    cases Option.some.inj found
    simp [same]
  next different => exact valid query value found

theorem projection_keys_keep_source_reference (geometry firstReference secondReference : Nat)
    (different : firstReference ≠ secondReference) :
    (geometry, firstReference) ≠ (geometry, secondReference) := by
  simp [different]

end PeriScribe.GeometryPreparation
