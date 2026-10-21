import PeriScribe.Grouping

namespace PeriScribe.RetainedSourceIndex

open Grouping

/-- A validated summary contains at most one complete evidence identity per occurrence. -/
def evidence (rows : List Edge) (node : Nat) : Option Nat :=
  (rows.find? fun row => row.1 == node).map Prod.snd

def changed (nodes : List Nat) (before after : List Edge) : List Nat :=
  nodes.filter fun node => evidence before node != evidence after node

theorem changed_exact (nodes : List Nat) (before after : List Edge) (node : Nat) :
    node ∈ changed nodes before after ↔
      node ∈ nodes ∧ evidence before node ≠ evidence after node := by
  simp [changed]

/-- Changed occurrences invalidate paths in both the retained and current incidence graph. -/
def Impacted (before after : List Edge) (changed : List Nat) (node : Nat) : Prop :=
  ∃ seed ∈ changed, Connected (before ++ after) seed node

/-- Executable equality of component labels evaluates the same finite path closure. -/
def isAffected (before after : List Edge) (changed : List Nat) (node : Nat) : Bool :=
  changed.any fun seed => labels (before ++ after) seed == labels (before ++ after) node

theorem affected_iff_impacted (before after : List Edge) (changed : List Nat)
    (node : Nat) : isAffected before after changed node = true ↔
      Impacted before after changed node := by
  simp only [isAffected, List.any_eq_true, beq_iff_eq, Impacted,
    union_computes_connected_components]

/-- Current occurrence filtering never rehydrates deleted occurrences. -/
def affected (current : List Nat) (before after : List Edge) (changed : List Nat) :
    List Nat :=
  current.filter (isAffected before after changed)

theorem affected_exact (current : List Nat) (before after : List Edge)
    (changed : List Nat) (node : Nat) :
    node ∈ affected current before after changed ↔
      node ∈ current ∧ Impacted before after changed node := by
  simp [affected, affected_iff_impacted]

theorem changed_is_impacted (before after : List Edge) (changed : List Nat)
    (seed : Nat) (member : seed ∈ changed) : Impacted before after changed seed :=
  ⟨seed, member, .same seed⟩

theorem unaffected_retains_complete_evidence (nodes : List Nat)
    (oldRows currentRows before after : List Edge) (node : Nat)
    (present : node ∈ nodes)
    (outside : ¬Impacted before after (changed nodes oldRows currentRows) node) :
    evidence oldRows node = evidence currentRows node := by
  by_cases equal : evidence oldRows node = evidence currentRows node
  · exact equal
  · have member := (changed_exact nodes oldRows currentRows node).mpr ⟨present, equal⟩
    exact False.elim (outside (changed_is_impacted before after _ node member))

theorem impact_follows_old_or_new_paths (before after : List Edge)
    (changed : List Nat) {left right : Nat}
    (impacted : Impacted before after changed left)
    (path : Connected (before ++ after) left right) :
    Impacted before after changed right := by
  rcases impacted with ⟨seed, member, initialPath⟩
  exact ⟨seed, member, .join initialPath path⟩

/-- No prior or current dependency can cross the dirty/clean boundary. -/
theorem closure_has_no_cut (before after : List Edge) (changed : List Nat)
    (edge : Edge) (member : edge ∈ before ++ after) :
    isAffected before after changed edge.1 = isAffected before after changed edge.2 := by
  have forward : Impacted before after changed edge.1 →
      Impacted before after changed edge.2 := fun impacted =>
    impact_follows_old_or_new_paths before after changed impacted (.edge member)
  have backward : Impacted before after changed edge.2 →
      Impacted before after changed edge.1 := fun impacted =>
    impact_follows_old_or_new_paths before after changed impacted (.reverse (.edge member))
  cases first : isAffected before after changed edge.1 <;>
    cases second : isAffected before after changed edge.2 <;> try rfl
  · have impacted := backward ((affected_iff_impacted _ _ _ _).mp second)
    have := (affected_iff_impacted _ _ _ _).mpr impacted
    simp [first] at this
  · have impacted := forward ((affected_iff_impacted _ _ _ _).mp first)
    have := (affected_iff_impacted _ _ _ _).mpr impacted
    simp [second] at this

/-- Reuse complete old clean blocks and rebuild the complete current dirty blocks. -/
def replacement (before after : List Edge) (dirty : Nat → Bool) : List Edge :=
  before.filter (fun edge => !(dirty edge.1)) ++ after.filter (fun edge => dirty edge.1)

/-- Complete unchanged evidence must preserve the actual edge relation outside closure. -/
theorem replacement_has_current_edges (before after : List Edge) (dirty : Nat → Bool)
    (stable : ∀ edge, dirty edge.1 = false → (edge ∈ before ↔ edge ∈ after))
    (edge : Edge) : edge ∈ replacement before after dirty ↔ edge ∈ after := by
  by_cases impacted : dirty edge.1 = true
  · simp [replacement, impacted]
  · have clean : dirty edge.1 = false := by cases value : dirty edge.1 <;> simp_all
    simpa [replacement, clean] using stable edge clean

/-- Incremental reconstruction agrees with an independent complete current graph. -/
theorem incremental_equals_full_index (before after : List Edge) (dirty : Nat → Bool)
    (stable : ∀ edge, dirty edge.1 = false → (edge ∈ before ↔ edge ∈ after))
    (left right : Nat) :
    labels (replacement before after dirty) left =
      labels (replacement before after dirty) right ↔
      labels after left = labels after right := by
  exact edge_order_and_duplicates_do_not_change_partition _ _
    (replacement_has_current_edges before after dirty stable) left right

/-- Conservative incidence and complete stable evidence discharge clean-edge stability. -/
theorem complete_summaries_preserve_full_index
    (nodes : List Nat) (oldRows currentRows oldDependencies currentDependencies
      oldEdges currentEdges : List Edge)
    (endpoints : ∀ edge ∈ oldEdges ++ currentEdges, edge.1 ∈ nodes ∧ edge.2 ∈ nodes)
    (conservative : ∀ edge ∈ oldEdges ++ currentEdges,
      edge ∈ oldDependencies ++ currentDependencies)
    (stable : ∀ edge,
      evidence oldRows edge.1 = evidence currentRows edge.1 →
      evidence oldRows edge.2 = evidence currentRows edge.2 →
      (edge ∈ oldEdges ↔ edge ∈ currentEdges)) (left right : Nat) :
    let dirty := isAffected oldDependencies currentDependencies (changed nodes oldRows currentRows)
    labels (replacement oldEdges currentEdges dirty) left =
      labels (replacement oldEdges currentEdges dirty) right ↔
      labels currentEdges left = labels currentEdges right := by
  apply incremental_equals_full_index
  intro edge clean
  by_cases present : edge ∈ oldEdges ++ currentEdges
  · have bounds := endpoints edge present
    have same := closure_has_no_cut oldDependencies currentDependencies
      (changed nodes oldRows currentRows) edge (conservative edge present)
    have rightClean : isAffected oldDependencies currentDependencies
        (changed nodes oldRows currentRows) edge.2 = false := same.symm.trans clean
    have oldEqual := unaffected_retains_complete_evidence nodes oldRows currentRows
      oldDependencies currentDependencies edge.1 bounds.1
      (fun impacted => by
        have actual := (affected_iff_impacted _ _ _ _).mpr impacted
        simp [clean] at actual)
    have newEqual := unaffected_retains_complete_evidence nodes oldRows currentRows
      oldDependencies currentDependencies edge.2 bounds.2
      (fun impacted => by
        have actual := (affected_iff_impacted _ _ _ _).mpr impacted
        simp [rightClean] at actual)
    exact stable edge oldEqual newEqual
  · have neither : edge ∉ oldEdges ∧ edge ∉ currentEdges := by simpa using present
    simp [neither.1, neither.2]

/-- An order-preserving compact rank selects the same original minimum in every subset. -/
theorem compact_rank_preserves_subset_minimum (catalogue subset : List Nat)
    (rank : Nat → Nat) (included : ∀ value ∈ subset, value ∈ catalogue)
    (ordered : ∀ left ∈ catalogue, ∀ right ∈ catalogue,
      rank left ≤ rank right ↔ left ≤ right)
    (chosen : Nat) (present : chosen ∈ subset) :
    (∀ value ∈ subset, rank chosen ≤ rank value) ↔
      (∀ value ∈ subset, chosen ≤ value) := by
  constructor
  · intro minimum value member
    exact (ordered chosen (included chosen present) value (included value member)).mp
      (minimum value member)
  · intro minimum value member
    exact (ordered chosen (included chosen present) value (included value member)).mpr
      (minimum value member)

end PeriScribe.RetainedSourceIndex
