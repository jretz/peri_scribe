import PeriScribe.Grouping
import PeriScribe.SparseEvidence

namespace PeriScribe.IdentityOutput

inductive Key where
  | identifier (value : Nat)
  | name (value : Nat)
  deriving DecidableEq, BEq, Repr

structure Observation where
  vertex : Nat
  identifier : Option Nat
  name : Nat
  time : Nat
  serial : Nat
  eligible : Bool
  area : Int
  deriving DecidableEq, Repr

/-- Tagged names cannot collide with identifiers with identical text. -/
def key (aliases : Nat → Nat) (row : Observation) : Key :=
  match row.identifier with
  | some identifier => .identifier (aliases identifier)
  | none => .name row.name

def history (aliases : Nat → Nat) (owner : Key) (rows : List Observation) :=
  rows.filter (fun row => decide (key aliases row = owner))

/-- Descriptive row lookup preserves its broader anonymous-name fallback contract. -/
def matched (identifiers : List Nat) (name : Nat) (rows : List Observation) :=
  rows.filter (fun row => if identifiers.isEmpty then row.name == name
    else row.identifier.any identifiers.contains)

theorem identified_lookup_never_falls_back (first : Nat) (rest : List Nat)
    (name : Nat) (rows : List Observation) (row : Observation)
    (selected : row ∈ matched (first :: rest) name rows) :
    ∃ identifier, row.identifier = some identifier ∧ identifier ∈ first :: rest := by
  have chosen := (List.mem_filter.mp selected).2
  cases found : row.identifier with
  | none => simp [found] at chosen
  | some identifier => exact ⟨identifier, rfl, by simpa [found] using chosen⟩

theorem name_lookup_can_include_identified_rows :
    let row : Observation := ⟨0, some 7, 3, 0, 0, true, 50⟩
    matched [] 3 [row] = [row] := by decide

theorem row_selection_preserves_chronology (identifiers : List Nat) (name : Nat)
    (rows : List Observation)
    (ordered : rows.Pairwise (fun first second => first.time ≤ second.time)) :
    (matched identifiers name rows).Pairwise
      (fun first second => first.time ≤ second.time) :=
  ordered.filter _

/-- Group membership determines ownership before area and drawing eligibility. -/
def grouped (edges : List Grouping.Edge) (owner : Nat) (rows : List Observation) :=
  rows.filter (fun row => Grouping.labels edges row.vertex == owner)

def chronological (rows : List Observation) : List Observation :=
  rows.mergeSort (fun first second => first.time ≤ second.time)

def drawable (edges : List Grouping.Edge) (owner : Nat) (rows : List Observation) :=
  chronological ((grouped edges owner rows).filter Observation.eligible)

def qualified (threshold : Int) (rows : List Observation) : Bool :=
  SparseEvidence.visible threshold (SparseEvidence.maximum (rows.map Observation.area))

theorem history_has_exact_canonical_owner (aliases : Nat → Nat) (owner : Key)
    (rows : List Observation) (row : Observation) :
    row ∈ history aliases owner rows ↔ row ∈ rows ∧ key aliases row = owner := by
  simp [history]

theorem canonical_ownership_is_unique (aliases : Nat → Nat) (first second : Key)
    (rows : List Observation) (row : Observation)
    (one : row ∈ history aliases first rows)
    (two : row ∈ history aliases second rows) : first = second := by
  have a := (history_has_exact_canonical_owner aliases first rows row).mp one
  have b := (history_has_exact_canonical_owner aliases second rows row).mp two
  exact a.2.symm.trans b.2

theorem identified_rows_never_enter_name_fallback (aliases : Nat → Nat)
    (rows : List Observation) (row : Observation) (identifier name : Nat)
    (known : row.identifier = some identifier) :
    row ∉ history aliases (.name name) rows := by
  simp [history, key, known]

theorem identifier_aliases_join_their_component (edges : List Grouping.Edge)
    (first second : Nat) (linked : Grouping.Connected edges first second) :
    Grouping.labels edges first = Grouping.labels edges second :=
  Grouping.labels_complete edges linked

theorem grouped_ownership_refines_connectivity (edges : List Grouping.Edge)
    (rows : List Observation) (row : Observation) (representative : Nat) :
    row ∈ grouped edges (Grouping.labels edges representative) rows ↔
      row ∈ rows ∧ Grouping.Connected edges row.vertex representative := by
  simp only [grouped, List.mem_filter, beq_iff_eq]
  rw [Grouping.union_computes_connected_components]

theorem drawing_preserves_every_eligible_observation (edges : List Grouping.Edge)
    (owner : Nat) (rows : List Observation) :
    (drawable edges owner rows).Perm
      ((grouped edges owner rows).filter Observation.eligible) :=
  List.mergeSort_perm _ _

theorem drawing_has_exact_eligible_members (edges : List Grouping.Edge)
    (owner : Nat) (rows : List Observation) (row : Observation) :
    row ∈ drawable edges owner rows ↔
      row ∈ rows ∧ Grouping.labels edges row.vertex = owner ∧ row.eligible = true := by
  simp [drawable, chronological, grouped, and_comm]

theorem distinct_components_cannot_share_drawn_evidence
    (edges : List Grouping.Edge) (rows : List Observation) (row : Observation)
    (first second : Nat)
    (one : row ∈ drawable edges (Grouping.labels edges first) rows)
    (two : row ∈ drawable edges (Grouping.labels edges second) rows) :
    Grouping.Connected edges first second := by
  have a := (drawing_has_exact_eligible_members edges _ rows row).mp one
  have b := (drawing_has_exact_eligible_members edges _ rows row).mp two
  exact Grouping.labels_sound edges first second (a.2.1.symm.trans b.2.1)

theorem drawings_are_chronological (edges : List Grouping.Edge)
    (owner : Nat) (rows : List Observation) :
    (drawable edges owner rows).Pairwise
      (fun first second => first.time ≤ second.time) := by
  apply List.Pairwise.imp (fun {_ _} ordered => of_decide_eq_true ordered)
  apply List.pairwise_mergeSort
  · intro first middle last one two
    exact decide_eq_true (Nat.le_trans (of_decide_eq_true one) (of_decide_eq_true two))
  · intro first second
    simp only [Bool.or_eq_true, decide_eq_true_eq]
    omega

theorem output_eligibility_has_owned_evidence (edges : List Grouping.Edge)
    (owner : Nat) (rows : List Observation) (threshold : Int) :
    qualified threshold (grouped edges owner rows) = true ↔
      ∃ row ∈ rows,
        Grouping.labels edges row.vertex = owner ∧ threshold ≤ row.area := by
  unfold qualified
  rw [SparseEvidence.visibility_has_witness]
  simp only [List.mem_map, grouped, List.mem_filter, beq_iff_eq]
  constructor
  · rintro ⟨area, ⟨row, ⟨member, owned⟩, same⟩, reaches⟩
    exact ⟨row, member, owned, by simpa [same] using reaches⟩
  · rintro ⟨row, member, owned, reaches⟩
    exact ⟨row.area, ⟨row, ⟨member, owned⟩, rfl⟩, reaches⟩

end PeriScribe.IdentityOutput
