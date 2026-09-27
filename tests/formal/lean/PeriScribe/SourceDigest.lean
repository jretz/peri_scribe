import Std

namespace PeriScribe.SourceDigest

/-- Zero is escaped so field boundaries cannot be supplied by source bytes. -/
def field : List Nat → List Nat
  | [] => [0, 0]
  | byte :: rest =>
    if byte = 0 then 0 :: 1 :: field rest else byte :: field rest

def readField : List Nat → Option (List Nat × List Nat)
  | 0 :: 0 :: rest => some ([], rest)
  | 0 :: 1 :: rest => do
    let (payload, suffix) ← readField rest
    return (0 :: payload, suffix)
  | 0 :: _ => none
  | byte :: rest => do
    let (payload, suffix) ← readField rest
    return (byte :: payload, suffix)
  | [] => none

theorem field_suffix (payload suffix : List Nat) :
    readField (field payload ++ suffix) = some (payload, suffix) := by
  induction payload with
  | nil => rfl
  | cons byte rest ih =>
    by_cases zero : byte = 0
    · subst byte
      simp [field, readField, ih]
    · cases byte with
      | zero => contradiction
      | succ byte => simp [field, readField, ih]

theorem field_injective (first second : List Nat)
    (same : field first = field second) : first = second := by
  have one := field_suffix first []
  have two := field_suffix second []
  rw [same] at one
  rw [two] at one
  exact (congrArg Prod.fst (Option.some.inj one)).symm

def fields (parts : List (List Nat)) : List Nat := parts.flatMap field

theorem fields_cons (head : List Nat) (tail : List (List Nat)) :
    fields (head :: tail) = field head ++ fields tail := rfl

theorem field_nonempty (payload : List Nat) : field payload ≠ [] := by
  cases payload with
  | nil => simp [field]
  | cons byte rest => simp only [field]; split <;> simp

theorem fields_empty_iff (parts : List (List Nat)) :
    fields parts = [] ↔ parts = [] := by
  cases parts with
  | nil => simp [fields]
  | cons head tail => simp [fields_cons, field_nonempty]

theorem fields_injective (first second : List (List Nat))
    (same : fields first = fields second) : first = second := by
  induction first generalizing second with
  | nil =>
    exact ((fields_empty_iff second).mp same.symm).symm
  | cons head tail ih =>
    cases second with
    | nil =>
      have := (fields_empty_iff (head :: tail)).mp same
      contradiction
    | cons other remaining =>
      have one := field_suffix head (fields tail)
      have two := field_suffix other (fields remaining)
      change field head ++ fields tail = field other ++ fields remaining at same
      rw [same, two] at one
      have pairs := Option.some.inj one
      have heads := congrArg Prod.fst pairs
      have tails := congrArg Prod.snd pairs
      simp only at heads tails
      rw [heads, ih remaining tails.symm]

theorem fields_equal_iff (first second : List (List Nat)) :
    fields first = fields second ↔ first = second :=
  ⟨fields_injective first second, congrArg fields⟩

theorem field_partition_distinct (a b c d : List Nat)
    (different : [a, b] ≠ [c, d]) : fields [a, b] ≠ fields [c, d] := by
  exact fun same => different (fields_injective _ _ same)

/-- CRS and ordered column labels remain visible even in a frame without rows. -/
def schema (reference : List Nat) (columns : List (List Nat)) : List Nat :=
  fields (reference :: columns)

theorem schema_equal_iff (a b : List Nat) (left right : List (List Nat)) :
    schema a left = schema b right ↔ a = b ∧ left = right := by
  simp [schema, fields_equal_iff]

theorem schema_rename_detected (reference : List Nat) (left right : List (List Nat))
    (different : left ≠ right) : schema reference left ≠ schema reference right := by
  intro same
  exact different ((schema_equal_iff _ _ _ _).mp same).2

/-- Natural tokens stand for fixed-width row hashes; multiplicity is retained. -/
def orderedRows (rows : List Nat) : List Nat := rows.mergeSort (· ≤ ·)

theorem ordered_rows_permutation (rows : List Nat) : (orderedRows rows).Perm rows :=
  List.mergeSort_perm _ _

theorem ordered_rows_sorted (rows : List Nat) :
    (orderedRows rows).Pairwise (· ≤ ·) := by
  have result := List.pairwise_mergeSort (le := fun a b : Nat => decide (a ≤ b))
    (fun a b c ab bc => by simp_all; omega) (fun a b => by simp; omega) rows
  simpa [orderedRows] using result

theorem permutation_same_rows (first second : List Nat) (same : first.Perm second) :
    orderedRows first = orderedRows second := by
  exact List.Perm.eq_of_pairwise (fun a b _ _ ab ba => Nat.le_antisymm ab ba)
    (ordered_rows_sorted first) (ordered_rows_sorted second)
    ((ordered_rows_permutation first).trans
      (same.trans (ordered_rows_permutation second).symm))

theorem same_rows_permutation (first second : List Nat)
    (same : orderedRows first = orderedRows second) : first.Perm second := by
  have result := ordered_rows_permutation first
  rw [same] at result
  exact result.symm.trans (ordered_rows_permutation second)

theorem row_order_irrelevant (first second : List Nat) :
    orderedRows first = orderedRows second ↔ first.Perm second :=
  ⟨same_rows_permutation first second, permutation_same_rows first second⟩

theorem row_count_preserved (rows : List Nat) (value : Nat) :
    (orderedRows rows).count value = rows.count value :=
  (ordered_rows_permutation rows).count_eq value

theorem added_duplicate_detected (rows : List Nat) (value : Nat) :
    orderedRows (value :: rows) ≠ orderedRows rows := by
  intro same
  have := congrArg List.length same
  simp [orderedRows] at this

def content (header : List Nat) (rows : List Nat) : List Nat × List Nat :=
  (header, orderedRows rows)

theorem content_equal_iff (a b first second : List Nat) :
    content a first = content b second ↔ a = b ∧ first.Perm second := by
  simp [content, row_order_irrelevant]

theorem empty_frames_retain_schema (first second : List Nat) :
    content first [] = content second [] ↔ first = second := by
  simp [content]

/-- Missing representations share a semantic token before field framing. -/
def normalized (value : Option (List Nat)) : List Nat :=
  match value with
  | none => [109]
  | some bytes => bytes

theorem normalized_missing : normalized none = [109] := rfl

theorem normalized_fields_agree (first second : List (Option (List Nat)))
    (same : first.map normalized = second.map normalized) :
    fields (first.map normalized) = fields (second.map normalized) :=
  congrArg fields same

end PeriScribe.SourceDigest
