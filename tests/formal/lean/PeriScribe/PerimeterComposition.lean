import PeriScribe.PerimeterVersions

namespace PeriScribe.PerimeterComposition

abbrev Observation := PerimeterVersions.Observation

/-- Missing keys differ from present nulls, which can mask a competing source field. -/
structure Policy where
  source : Option Nat := none
  sourceAlias : Option Nat := none
  category : Option Nat := none
  categoryAlias : Option Nat := none
  capture : Option (Option Nat × Bool) := none
  deriving Repr

def mergePolicy (winner loser : Policy) : Policy :=
  ⟨winner.source.or loser.source, winner.sourceAlias.or loser.sourceAlias,
    winner.category.or loser.category, winner.categoryAlias.or loser.categoryAlias,
    winner.capture.or loser.capture⟩

/-- Source attributes can change later revision and delayed-copy decisions. -/
structure Entry where
  observation : Observation
  attributes : Nat → Option Nat
  measured : Nat
  policy : Policy := {}

def lineage (entry : Entry) : List Nat := PerimeterVersions.lineage entry.observation

def covered (entries : List Entry) (source : Nat) : Prop :=
  ∃ entry ∈ entries, source ∈ lineage entry

def inherit (winner loser : Entry) : Entry :=
  { winner with observation := (PerimeterVersions.inherit
    winner.observation loser.observation) }

def normalized (entry : Entry) : Entry :=
  let source := (entry.policy.source.filter (fun value => 0 < value)).or
    (entry.policy.sourceAlias.filter (fun value => 0 < value))
  let category := (entry.policy.category.filter (fun value => 0 < value)).or
    (entry.policy.categoryAlias.filter (fun value => 0 < value))
  let capture := entry.policy.capture.getD (none, true)
  { entry with observation := {
      entry.observation with
      source := source.getD 0
      category := category.getD 0
      capture := capture.1
      captureSameYear := capture.2
      flight := entry.policy.source == some 1 } }

def merge (winner loser : Entry) : Entry :=
  normalized {
    inherit winner loser with
    attributes := fun key => (winner.attributes key).or (loser.attributes key)
    policy := mergePolicy winner.policy loser.policy }

theorem inherit_conserves_provenance (winner loser : Entry) (source : Nat) :
    source ∈ lineage (inherit winner loser) ↔
      source ∈ lineage winner ∨ source ∈ lineage loser := by
  exact PerimeterVersions.inheritance_conserves_all_provenance _ _ _

theorem merge_conserves_provenance (winner loser : Entry) (source : Nat) :
    source ∈ lineage (merge winner loser) ↔
      source ∈ lineage winner ∨ source ∈ lineage loser := by
  exact inherit_conserves_provenance winner loser source

theorem merged_attribute_keeps_winner (winner loser : Entry) (key value : Nat)
    (present : winner.attributes key = some value) :
    (merge winner loser).attributes key = some value := by
  simp [merge, normalized, present]

theorem merged_attribute_fills_only_absence (winner loser : Entry) (key : Nat)
    (absent : winner.attributes key = none) :
    (merge winner loser).attributes key = loser.attributes key := by
  simp [merge, normalized, absent]

theorem merged_attribute_has_source (winner loser : Entry) (key value : Nat)
    (selected : (merge winner loser).attributes key = some value) :
    winner.attributes key = some value ∨ loser.attributes key = some value := by
  cases found : winner.attributes key with
  | none => exact Or.inr (by simpa [merge, normalized, found] using selected)
  | some previous => exact Or.inl (by simpa [merge, normalized, found] using selected)

theorem merge_keeps_winners_geometry_and_measurement (winner loser : Entry) :
    (merge winner loser).observation.start = winner.observation.start ∧
      (merge winner loser).observation.width = winner.observation.width ∧
      (merge winner loser).measured = winner.measured := by
  simp [merge, normalized, inherit, PerimeterVersions.inherit]

theorem present_null_source_keeps_its_key (winner loser : Entry)
    (present : winner.policy.source = some 0) :
    (merge winner loser).policy.source = some 0 := by
  simp [merge, normalized, mergePolicy, present]

theorem absent_capture_inherits_losing_capture (winner loser : Entry)
    (absent : winner.policy.capture = none) :
    (merge winner loser).observation.capture =
      (loser.policy.capture.getD (none, true)).1 := by
  simp [merge, normalized, mergePolicy, absent]

def before (first second : Entry) : Bool :=
  decide (first.observation.time < second.observation.time ∨
    (first.observation.time = second.observation.time ∧
      (first.observation.serial < second.observation.serial ∨
        (first.observation.serial = second.observation.serial ∧
          first.observation.object ≤ second.observation.object))))

def ordered (entries : List Entry) : List Entry := entries.mergeSort before

theorem ordering_conserves_provenance (entries : List Entry) (source : Nat) :
    covered (ordered entries) source ↔ covered entries source := by
  simp [ordered, covered]

def collapseStep (retained : List Entry) (current : Entry) : List Entry :=
  match retained with
  | [] => [current]
  | previous :: rest =>
    if PerimeterVersions.sameShape previous.observation current.observation &&
        !PerimeterVersions.newCapture previous.observation current.observation then
      { inherit current previous with observation :=
          { (inherit current previous).observation with
            time := previous.observation.time } } :: rest
    else current :: retained

def collapse (entries : List Entry) : List Entry :=
  ((ordered entries).foldl collapseStep []).reverse

theorem collapse_step_conserves_provenance (retained : List Entry)
    (current : Entry) (source : Nat) :
    covered (collapseStep retained current) source ↔
      covered retained source ∨ source ∈ lineage current := by
  cases retained with
  | nil => simp [collapseStep, covered]
  | cons previous rest =>
    simp only [collapseStep]
    split
    · simp only [covered, List.mem_cons, exists_eq_or_imp]
      change (source ∈ lineage (inherit current previous) ∨ _) ↔ _
      rw [inherit_conserves_provenance]
      simp only [or_assoc, or_comm]
    · simp [covered, or_comm]

theorem collapse_fold_conserves_provenance (entries retained : List Entry)
    (source : Nat) :
    covered (entries.foldl collapseStep retained) source ↔
      covered retained source ∨ covered entries source := by
  induction entries generalizing retained with
  | nil => simp [covered]
  | cons current rest induction =>
    rw [List.foldl_cons, induction, collapse_step_conserves_provenance]
    simp [covered, or_assoc, or_left_comm, or_comm]

theorem collapse_conserves_provenance (entries : List Entry) (source : Nat) :
    covered (collapse entries) source ↔ covered entries source := by
  simp only [collapse, covered, List.mem_reverse]
  change covered ((ordered entries).foldl collapseStep []) source ↔ _
  rw [collapse_fold_conserves_provenance, ordering_conserves_provenance]
  simp [covered]

def sameVersion (first second : Entry) : Bool :=
  PerimeterVersions.sameShape first.observation second.observation &&
    PerimeterVersions.contemporaneous first.observation second.observation

def mergeOne (preferred : Nat) (current : Entry) : List Entry → List Entry
  | [] => [current]
  | existing :: rest =>
    if sameVersion existing current then
      (if existing.observation.feed == preferred then merge existing current
        else merge current existing) :: rest
    else existing :: mergeOne preferred current rest

def mergeIdentical (preferred : Nat) (entries : List Entry) : List Entry :=
  entries.foldl (fun retained current => mergeOne preferred current retained) []

theorem merge_one_conserves_provenance (preferred : Nat) (current : Entry)
    (entries : List Entry) (source : Nat) :
    covered (mergeOne preferred current entries) source ↔
      covered entries source ∨ source ∈ lineage current := by
  induction entries with
  | nil => simp [mergeOne, covered]
  | cons first rest induction =>
    simp only [mergeOne]
    split
    · split <;>
        simp only [covered, List.mem_cons, exists_eq_or_imp] <;>
        rw [merge_conserves_provenance] <;>
        simp only [or_assoc, or_comm]
    · simp only [covered, List.mem_cons, exists_eq_or_imp] at *
      rw [induction]
      simp only [or_assoc]

theorem merge_fold_conserves_provenance (preferred : Nat)
    (entries retained : List Entry) (source : Nat) :
    covered (entries.foldl (fun old current => mergeOne preferred current old) retained)
      source ↔ covered retained source ∨ covered entries source := by
  induction entries generalizing retained with
  | nil => simp [covered]
  | cons current rest induction =>
    rw [List.foldl_cons, induction, merge_one_conserves_provenance]
    simp [covered, or_assoc]

theorem merge_identical_conserves_provenance (preferred : Nat) (entries : List Entry)
    (source : Nat) :
    covered (mergeIdentical preferred entries) source ↔ covered entries source := by
  rw [mergeIdentical, merge_fold_conserves_provenance]
  simp [covered]

def absorb (current : Entry) : List Entry → Option (List Entry)
  | [] => none
  | first :: rest =>
    if PerimeterVersions.canReplace current.observation first.observation then
      some (inherit first current :: rest)
    else (absorb current rest).map (first :: ·)

theorem absorbed_has_witness (current : Entry) (preferred result : List Entry)
    (replaced : absorb current preferred = some result) :
    ∃ witness ∈ preferred,
      PerimeterVersions.canReplace current.observation witness.observation = true := by
  induction preferred generalizing result with
  | nil => simp [absorb] at replaced
  | cons first rest induction =>
    simp only [absorb] at replaced
    split at replaced
    next eligible => exact ⟨first, by simp, eligible⟩
    next =>
      rcases Option.map_eq_some_iff.mp replaced with ⟨later, replaced, _⟩
      rcases induction later replaced with ⟨witness, present, valid⟩
      exact ⟨witness, by simp [present], valid⟩

theorem absorb_conserves_provenance (current : Entry) (preferred result : List Entry)
    (replaced : absorb current preferred = some result) (source : Nat) :
    covered result source ↔ covered preferred source ∨ source ∈ lineage current := by
  induction preferred generalizing result with
  | nil => simp [absorb] at replaced
  | cons first rest induction =>
    simp only [absorb] at replaced
    split at replaced
    · cases Option.some.inj replaced
      simp only [covered, List.mem_cons, exists_eq_or_imp]
      rw [inherit_conserves_provenance]
      simp only [or_assoc, or_comm]
    · rcases Option.map_eq_some_iff.mp replaced with ⟨later, changed, same⟩
      cases same
      have remaining := induction later changed
      simp only [covered, List.mem_cons, exists_eq_or_imp] at *
      rw [remaining]
      simp only [or_assoc]

/-- Each competitor either keeps a row or transfers its lineage to an eligible row. -/
def absorbAll : List Entry → List Entry → List Entry
  | [], preferred => preferred
  | current :: rest, preferred =>
    match absorb current preferred with
    | none => current :: absorbAll rest preferred
    | some updated => absorbAll rest updated

theorem outer_absorption_conserves_provenance (competing preferred : List Entry)
    (source : Nat) :
    covered (absorbAll competing preferred) source ↔
      covered competing source ∨ covered preferred source := by
  induction competing generalizing preferred with
  | nil => simp [absorbAll, covered]
  | cons current rest induction =>
    simp only [absorbAll]
    split
    · simp only [covered, List.mem_cons, exists_eq_or_imp] at *
      rw [induction]
      simp [or_assoc]
    next updated changed =>
      rw [induction, absorb_conserves_provenance current preferred updated changed]
      simp [covered, or_assoc, or_left_comm, or_comm]

def dropCompeting (preferred : Nat) (entries : List Entry) : List Entry :=
  ordered (absorbAll (entries.filter (fun entry => entry.observation.feed != preferred))
    ((entries.filter (fun entry => entry.observation.feed == preferred)).mergeSort
      (fun first second => before second first)))

theorem drop_competing_conserves_provenance (preferred : Nat) (entries : List Entry)
    (source : Nat) :
    covered (dropCompeting preferred entries) source ↔ covered entries source := by
  rw [dropCompeting, ordering_conserves_provenance,
    outer_absorption_conserves_provenance]
  simp only [covered, List.mem_mergeSort, List.mem_filter]
  constructor
  · rintro (⟨entry, member, present⟩ | ⟨entry, member, present⟩) <;>
      exact ⟨entry, member.1, present⟩
  · rintro ⟨entry, member, present⟩
    by_cases same : entry.observation.feed = preferred
    · exact Or.inr ⟨entry, ⟨member, by simp [same]⟩, present⟩
    · exact Or.inl ⟨entry, ⟨member, by simp [same]⟩, present⟩

structure RevisionGroup where
  anchor : Entry
  retained : Entry

def revisionWinner (previous current : Entry) : Entry :=
  if PerimeterVersions.laterPublication previous.observation current.observation then
    inherit current previous else inherit previous current

def revisionStep (groups : List RevisionGroup) (current : Entry) : List RevisionGroup :=
  match groups with
  | [] => [⟨current, current⟩]
  | previous :: rest =>
    if PerimeterVersions.revisionPair previous.anchor.observation current.observation &&
        PerimeterVersions.revisionPair previous.retained.observation
          current.observation then
      ⟨previous.anchor, revisionWinner previous.retained current⟩ :: rest
    else ⟨current, current⟩ :: groups

def revisions (entries : List Entry) : List Entry :=
  ((entries.foldl revisionStep []).reverse).map RevisionGroup.retained

theorem revision_winner_conserves_provenance (previous current : Entry) (source : Nat) :
    source ∈ lineage (revisionWinner previous current) ↔
      source ∈ lineage previous ∨ source ∈ lineage current := by
  unfold revisionWinner
  split <;> rw [inherit_conserves_provenance] <;> simp only [or_comm]

theorem revision_step_conserves_provenance (groups : List RevisionGroup)
    (current : Entry) (source : Nat) :
    covered ((revisionStep groups current).map RevisionGroup.retained) source ↔
      covered (groups.map RevisionGroup.retained) source ∨
        source ∈ lineage current := by
  cases groups with
  | nil => simp [revisionStep, covered]
  | cons previous rest =>
    simp only [revisionStep]
    split
    · simp only [List.map_cons, covered, List.mem_cons, exists_eq_or_imp]
      rw [revision_winner_conserves_provenance]
      simp only [or_assoc, or_comm]
    · simp [covered, or_comm]

theorem revision_fold_conserves_provenance (entries : List Entry)
    (groups : List RevisionGroup) (source : Nat) :
    covered ((entries.foldl revisionStep groups).map RevisionGroup.retained) source ↔
      covered (groups.map RevisionGroup.retained) source ∨ covered entries source := by
  induction entries generalizing groups with
  | nil => simp [covered]
  | cons current rest induction =>
    rw [List.foldl_cons, induction, revision_step_conserves_provenance]
    simp [covered, or_assoc]

theorem revisions_conserve_provenance (entries : List Entry) (source : Nat) :
    covered (revisions entries) source ↔ covered entries source := by
  simp only [revisions, List.map_reverse, covered, List.mem_reverse]
  change covered ((entries.foldl revisionStep []).map RevisionGroup.retained) source ↔ _
  rw [revision_fold_conserves_provenance]
  simp [covered]

/-- Keys zero and one are normalized positive computed and incident acreages. -/
def implausible (entry : Entry) : Bool :=
  (entry.attributes 0).any (fun computed => decide (0 < computed ∧
    100 * entry.measured < 20 * computed)) ||
    (entry.attributes 1).any (fun incident => decide (0 < incident ∧
      100 * entry.measured < incident))

def reconciled (preferred : Nat) (entries : List Entry) : List Entry :=
  ordered (revisions (dropCompeting preferred (mergeIdentical preferred (ordered
    (collapse (entries.filter (fun entry => entry.observation.feed == 0)) ++
      collapse (entries.filter (fun entry => entry.observation.feed == 1)))))))

def reconcile (preferred : Nat) (entries : List Entry) : List Entry :=
  (reconciled preferred entries).filter (fun entry => !implausible entry)

theorem complete_reconciliation_conserves_source_lineage (preferred : Nat)
    (entries : List Entry) (feeds : ∀ entry ∈ entries,
      entry.observation.feed = 0 ∨ entry.observation.feed = 1) (source : Nat) :
    covered (reconciled preferred entries) source ↔ covered entries source := by
  simp only [reconciled, ordering_conserves_provenance, revisions_conserve_provenance,
    drop_competing_conserves_provenance, merge_identical_conserves_provenance]
  have append : ∀ first second : List Entry,
      covered (first ++ second) source ↔
        covered first source ∨ covered second source := by
    intro first second
    simp [covered, or_and_right, exists_or]
  rw [append, collapse_conserves_provenance, collapse_conserves_provenance]
  simp only [covered, List.mem_filter]
  constructor
  · rintro (⟨entry, member, present⟩ | ⟨entry, member, present⟩) <;>
      exact ⟨entry, member.1, present⟩
  · rintro ⟨entry, member, present⟩
    rcases feeds entry member with first | second
    · exact Or.inl ⟨entry, ⟨member, by simp [first]⟩, present⟩
    · exact Or.inr ⟨entry, ⟨member, by simp [second]⟩, present⟩

theorem final_output_has_a_retained_witness (preferred : Nat) (entries : List Entry)
    (entry : Entry) (present : entry ∈ reconcile preferred entries) :
    entry ∈ reconciled preferred entries ∧ implausible entry = false := by
  simpa [reconcile] using List.mem_filter.mp present

theorem lineage_loss_requires_a_rejected_witness (preferred : Nat)
    (entries : List Entry) (feeds : ∀ entry ∈ entries,
      entry.observation.feed = 0 ∨ entry.observation.feed = 1) (source : Nat)
    (input : covered entries source)
    (absent : ¬covered (reconcile preferred entries) source) :
    ∃ entry ∈ reconciled preferred entries,
      source ∈ lineage entry ∧ implausible entry = true := by
  rcases (complete_reconciliation_conserves_source_lineage preferred entries feeds
    source).mpr input with ⟨entry, member, present⟩
  refine ⟨entry, member, present, ?_⟩
  cases rejected : implausible entry with
  | true => rfl
  | false =>
    exact False.elim (absent ⟨entry, by simp [reconcile, member, rejected], present⟩)

theorem output_is_chronological (preferred : Nat) (entries : List Entry) :
    (reconcile preferred entries).Pairwise
      (fun first second => first.observation.time ≤ second.observation.time) := by
  apply List.Pairwise.filter
  have sorted : ((reconciled preferred entries)).Pairwise
      (fun first second => before first second = true) := by
    unfold reconciled ordered
    apply List.pairwise_mergeSort
    · intro first second third left right
      simp only [before, decide_eq_true_eq] at *
      omega
    · intro first second
      simp only [before, Bool.or_eq_true, decide_eq_true_eq]
      omega
  exact sorted.imp (by
    intro first second relation
    simp only [before, decide_eq_true_eq] at relation
    omega)

end PeriScribe.PerimeterComposition
