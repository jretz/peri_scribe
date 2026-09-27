import Std

namespace PeriScribe.SourceValidation

/-- Attribute and shape tokens denote normalized values and topological equivalence. -/
structure Row where
  key : Nat
  attributes : List (Nat × Nat)
  geometry : Nat
  deriving DecidableEq, Repr

structure Frame where
  columns : List Nat
  reference : Option Nat
  rows : List Row
  deriving DecidableEq, Repr

def value (row : Row) (column : Nat) : Option Nat :=
  (row.attributes.find? (fun item => item.1 == column)).map Prod.snd

def sameContent (columns : List Nat) (first second : Row) : Bool :=
  first.geometry == second.geometry &&
    columns.all (fun column => value first column == value second column)

def lookup (rows : List Row) (key : Nat) : Option Row :=
  rows.find? (fun row => row.key == key)

def covered (columns : List Nat) (rows : List Row) (row : Row) : Bool :=
  match lookup rows row.key with
  | none => false
  | some stored => sameContent columns row stored

def compatible (complete stored : Frame) : Bool :=
  complete.reference.isSome && complete.reference == stored.reference

def accepts (complete stored : Frame) : Bool :=
  compatible complete stored && decide (complete.rows.map Row.key).Nodup &&
    decide (stored.rows.map Row.key).Nodup &&
    complete.columns.all (fun column => stored.columns.contains column) &&
    complete.rows.all (covered complete.columns stored.rows)

def duplicates (rows : List Row) : List Nat :=
  let keys := rows.map Row.key
  keys.eraseDups.filter (fun key => 1 < keys.count key)

def missing (complete stored : Frame) : List Nat :=
  (complete.rows.map Row.key).eraseDups.filter
    (fun key => !(stored.rows.any (fun row => row.key == key)))

def missingColumns (complete stored : Frame) : List Nat :=
  complete.columns.eraseDups.filter (fun column => !stored.columns.contains column)

def mismatched (complete stored : Frame) : List Nat :=
  (complete.rows.map Row.key).eraseDups.filter fun key =>
    match lookup complete.rows key, lookup stored.rows key with
    | some first, some second =>
      (duplicates complete.rows).contains key ||
        (duplicates stored.rows).contains key ||
        !(sameContent
          (complete.columns.filter (fun column => stored.columns.contains column))
          first second)
    | _, _ => false

theorem content_exact (columns : List Nat) (first second : Row) :
    sameContent columns first second = true ↔ first.geometry = second.geometry ∧
      ∀ column ∈ columns, value first column = value second column := by
  simp [sameContent]

theorem lookup_has_matching_witness (rows : List Row) (key : Nat) (row : Row)
    (found : lookup rows key = some row) : row ∈ rows ∧ row.key = key := by
  exact ⟨List.mem_of_find?_eq_some found, by simpa using List.find?_some found⟩

theorem covered_has_complete_witness (columns : List Nat) (rows : List Row) (row : Row)
    (yes : covered columns rows row = true) :
    ∃ stored ∈ rows, stored.key = row.key ∧ stored.geometry = row.geometry ∧
      ∀ column ∈ columns, value stored column = value row column := by
  cases found : lookup rows row.key with
  | none => simp [covered, found] at yes
  | some stored =>
    have witness := lookup_has_matching_witness rows row.key stored found
    have equal := (content_exact columns row stored).mp
      (by simpa [covered, found] using yes)
    exact ⟨stored, witness.1, witness.2, equal.1.symm,
      fun column present => (equal.2 column present).symm⟩

theorem accepted_requirements (complete stored : Frame)
    (yes : accepts complete stored = true) :
    compatible complete stored = true ∧ (complete.rows.map Row.key).Nodup ∧
      (stored.rows.map Row.key).Nodup ∧
      (∀ column ∈ complete.columns, column ∈ stored.columns) ∧
      ∀ row ∈ complete.rows, covered complete.columns stored.rows row = true := by
  simpa [accepts, and_assoc] using yes

theorem accepted_reference_is_known_and_equal (complete stored : Frame)
    (yes : accepts complete stored = true) :
    ∃ reference, complete.reference = some reference ∧
      stored.reference = some reference := by
  have compatible := (accepted_requirements complete stored yes).1
  cases known : complete.reference with
  | none => simp [SourceValidation.compatible, known] at compatible
  | some reference =>
    have equal : some reference = stored.reference := by
      simpa [SourceValidation.compatible, known] using compatible
    exact ⟨reference, rfl, equal.symm⟩

theorem success_covers_every_complete_row (complete stored : Frame)
    (yes : accepts complete stored = true) (row : Row) (present : row ∈ complete.rows) :
    ∃ witness ∈ stored.rows, witness.key = row.key ∧ witness.geometry = row.geometry ∧
      ∀ column ∈ complete.columns, value witness column = value row column := by
  exact covered_has_complete_witness _ _ row
    ((accepted_requirements complete stored yes).2.2.2.2 row present)

theorem unique_lookup_retains_row (rows : List Row)
    (unique : (rows.map Row.key).Nodup) (row : Row) (present : row ∈ rows) :
    lookup rows row.key = some row := by
  induction rows with
  | nil => simp at present
  | cons first rest ih =>
    have distinct : first.key ∉ rest.map Row.key ∧ (rest.map Row.key).Nodup := by
      simpa using unique
    rcases List.mem_cons.mp present with same | later
    · subst row; simp [lookup]
    · have different : first.key ≠ row.key := by
        intro same
        exact distinct.1 (by simp only [List.mem_map]; exact ⟨row, later, same.symm⟩)
      simpa only [lookup, List.find?_cons, beq_eq_false_iff_ne.mpr different,
        Bool.false_eq_true, ↓reduceIte] using ih distinct.2 later

theorem witness_implies_covered (columns : List Nat) (rows : List Row)
    (row stored : Row)
    (unique : (rows.map Row.key).Nodup) (present : stored ∈ rows)
    (key : stored.key = row.key) (shape : stored.geometry = row.geometry)
    (values : ∀ column ∈ columns, value stored column = value row column) :
    covered columns rows row = true := by
  have found := unique_lookup_retains_row rows unique stored present
  rw [key] at found
  simp only [covered, found]
  exact (content_exact _ _ _).mpr ⟨shape.symm,
    fun column present => (values column present).symm⟩

/-- An independent relational contract does not use indexed lookups. -/
def CompleteCoverage (complete stored : Frame) : Prop :=
  (∃ reference, complete.reference = some reference ∧
    stored.reference = some reference) ∧
    (complete.rows.map Row.key).Nodup ∧ (stored.rows.map Row.key).Nodup ∧
    (∀ column ∈ complete.columns, column ∈ stored.columns) ∧
    ∀ row ∈ complete.rows, ∃ witness ∈ stored.rows,
      witness.key = row.key ∧ witness.geometry = row.geometry ∧
        ∀ column ∈ complete.columns, value witness column = value row column

theorem indexed_validation_equals_relational_coverage (complete stored : Frame) :
    accepts complete stored = true ↔ CompleteCoverage complete stored := by
  constructor
  · intro yes
    have requirements := accepted_requirements complete stored yes
    exact ⟨accepted_reference_is_known_and_equal complete stored yes,
      requirements.2.1, requirements.2.2.1, requirements.2.2.2.1,
      success_covers_every_complete_row complete stored yes⟩
  · rintro ⟨⟨reference, first, second⟩, firstUnique, secondUnique, columns, witnesses⟩
    have rows : ∀ row ∈ complete.rows,
        covered complete.columns stored.rows row = true := by
      intro row present
      obtain ⟨witness, found, key, shape, values⟩ := witnesses row present
      exact witness_implies_covered _ _ _ _ secondUnique found key shape values
    simpa [accepts, compatible, first, second, firstUnique, secondUnique] using
      And.intro columns rows

theorem unknown_reference_cannot_succeed (complete stored : Frame)
    (unknown : complete.reference = none) : accepts complete stored = false := by
  simp [accepts, compatible, unknown]

theorem different_references_cannot_succeed (complete stored : Frame)
    (different : complete.reference ≠ stored.reference) :
    accepts complete stored = false := by
  simp [accepts, compatible, different]

theorem repeated_complete_keys_cannot_succeed (complete stored : Frame)
    (repeated : ¬ (complete.rows.map Row.key).Nodup) :
    accepts complete stored = false := by
  simp [accepts, repeated]

theorem repeated_stored_keys_cannot_succeed (complete stored : Frame)
    (repeated : ¬ (stored.rows.map Row.key).Nodup) :
    accepts complete stored = false := by
  simp [accepts, repeated]

theorem row_permutations_preserve_success (complete stored : Frame)
    (first second : List Row) (one : first.Perm complete.rows)
    (two : second.Perm stored.rows) :
    accepts { complete with rows := first } { stored with rows := second } =
      accepts complete stored := by
  apply Bool.eq_iff_iff.mpr
  rw [indexed_validation_equals_relational_coverage,
    indexed_validation_equals_relational_coverage]
  simp only [CompleteCoverage]
  have firstUnique := (one.map Row.key).nodup_iff
  have secondUnique := (two.map Row.key).nodup_iff
  simp only [firstUnique, secondUnique, one.mem_iff, two.mem_iff]

theorem valid_frame_covers_itself (frame : Frame) (reference : Nat)
    (known : frame.reference = some reference)
    (unique : (frame.rows.map Row.key).Nodup) :
    accepts frame frame = true := by
  apply (indexed_validation_equals_relational_coverage _ _).mpr
  exact ⟨⟨reference, known, known⟩, unique, unique, fun _ present => present,
    fun row present => ⟨row, present, rfl, rfl, fun _ _ => rfl⟩⟩

theorem extra_stored_content_preserves_success (complete stored extended : Frame)
    (yes : accepts complete stored = true)
    (reference : extended.reference = stored.reference)
    (columns : ∀ column ∈ stored.columns, column ∈ extended.columns)
    (rows : ∀ row ∈ stored.rows, row ∈ extended.rows)
    (unique : (extended.rows.map Row.key).Nodup) :
    accepts complete extended = true := by
  obtain ⟨⟨known, first, second⟩, firstUnique, _, allColumns, witnesses⟩ :=
    (indexed_validation_equals_relational_coverage complete stored).mp yes
  apply (indexed_validation_equals_relational_coverage _ _).mpr
  refine ⟨⟨known, first, reference.trans second⟩, firstUnique, unique,
    fun column present => columns column (allColumns column present), ?_⟩
  intro row present
  obtain ⟨witness, found, key, shape, values⟩ := witnesses row present
  exact ⟨witness, rows witness found, key, shape, values⟩

end PeriScribe.SourceValidation
