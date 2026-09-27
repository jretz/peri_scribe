namespace PeriScribe.CacheDependencies

abbrev Inputs := Nat → Nat

/-- A structured preimage; cryptographic collision resistance is outside this model. -/
def signature (fields : List Nat) (inputs : Inputs) :=
  fields.map (fun field => (field, inputs field))

def agrees (fields : List Nat) (first second : Inputs) : Prop :=
  ∀ field ∈ fields, first field = second field

def complete (required keyed : List Nat) : Prop :=
  ∀ field ∈ required, field ∈ keyed

theorem executable_completeness (required keyed : List Nat) :
    required.all keyed.contains = true ↔ complete required keyed := by
  simp [List.all_eq_true, complete]

theorem signature_equality_iff (fields : List Nat) (first second : Inputs) :
    signature fields first = signature fields second ↔ agrees fields first second := by
  induction fields with
  | nil => simp [signature, agrees]
  | cons field rest ih =>
    simp only [signature, List.map_cons, List.cons.injEq, Prod.mk.injEq, true_and]
    change first field = second field ∧ signature rest first = signature rest second ↔ _
    rw [ih]
    simp [agrees]

theorem complete_keys_preserve_dependencies (required keyed : List Nat)
    (included : complete required keyed) (first second : Inputs)
    (hit : signature keyed first = signature keyed second) :
    signature required first = signature required second := by
  apply (signature_equality_iff required first second).mpr
  intro field member
  exact (signature_equality_iff keyed first second).mp hit field (included field member)

/-- Equal keys preserve every deterministic product of the declared dependencies. -/
theorem warm_equals_fresh {Result : Type} (required keyed : List Nat)
    (included : complete required keyed) (render : List (Nat × Nat) → Result)
    (first second : Inputs) (hit : signature keyed first = signature keyed second) :
    render (signature required first) = render (signature required second) := by
  rw [complete_keys_preserve_dependencies required keyed included first second hit]

def changed (field : Nat) : Inputs := fun other => if other = field then 1 else 0

theorem omitted_dependency_admits_false_hit (required keyed : List Nat) (field : Nat)
    (needed : field ∈ required) (omitted : field ∉ keyed) :
    signature keyed (fun _ => 0) = signature keyed (changed field) ∧
    signature required (fun _ => 0) ≠ signature required (changed field) := by
  constructor
  · apply (signature_equality_iff keyed _ _).mpr
    intro other member
    have distinct : other ≠ field := by intro same; subst other; exact omitted member
    simp [changed, distinct]
  · intro same
    have impossible := (signature_equality_iff required _ _).mp same field needed
    simp [changed] at impossible

theorem completeness_is_necessary_and_sufficient (required keyed : List Nat) :
    complete required keyed ↔ ∀ first second,
      signature keyed first = signature keyed second →
      signature required first = signature required second := by
  constructor
  · exact fun included => complete_keys_preserve_dependencies required keyed included
  · intro preserves field needed
    by_cases included : field ∈ keyed
    · exact included
    · obtain ⟨hit, miss⟩ := omitted_dependency_admits_false_hit required keyed
        field needed included
      exact False.elim (miss (preserves _ _ hit))

theorem composed_keys_cover_transitive_dependencies
    (first second keyed : List Nat)
    (one : complete first keyed) (two : complete second keyed) :
    complete (first ++ second) keyed := by
  intro field member
  rcases List.mem_append.mp member with member | member
  · exact one field member
  · exact two field member

theorem irrelevant_inputs_may_reuse (required : List Nat) (field : Nat)
    (irrelevant : field ∉ required) :
    signature required (fun _ => 0) = signature required (changed field) := by
  apply (signature_equality_iff required _ _).mpr
  intro other member
  have distinct : other ≠ field := by intro same; subst other; exact irrelevant member
  simp [changed, distinct]

/-- Current wrapper fields are reattached after content reuse. -/
theorem live_wrapper {Content Wrapper : Type} (content : Content)
    (old current : Wrapper) (different : old ≠ current) :
    (content, old) ≠ (content, current) := by
  simp [different]

def check (required keyed : List Nat) (first second : List Nat) : List Nat :=
  let input := fun values field => (values[field]?).getD 0
  [if required.all keyed.contains then 1 else 0,
   if signature keyed (input first) = signature keyed (input second) then 1 else 0,
   if signature required (input first) = signature required (input second)
     then 1 else 0]

end PeriScribe.CacheDependencies
