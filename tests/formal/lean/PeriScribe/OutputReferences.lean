import Std

namespace PeriScribe.OutputReferences

/-- Candidate tokens preserve equality after slugging, including suffix collisions. -/
def allocate (used candidates : List Nat) : Option Nat :=
  candidates.find? (fun candidate => !used.contains candidate)

theorem allocated_is_fresh (used candidates : List Nat) (name : Nat)
    (chosen : allocate used candidates = some name) : name ∉ used := by
  simpa [allocate] using List.find?_some chosen

theorem allocated_is_candidate (used candidates : List Nat) (name : Nat)
    (chosen : allocate used candidates = some name) : name ∈ candidates :=
  List.mem_of_find?_eq_some chosen

theorem candidate_witness_guarantees_allocation (used candidates : List Nat)
    (name : Nat) (member : name ∈ candidates) (fresh : name ∉ used) :
    (allocate used candidates).isSome = true := by
  apply List.find?_isSome.mpr
  exact ⟨name, member, by simpa using fresh⟩

theorem more_candidates_guarantees_allocation (used candidates : List Nat)
    (unique : candidates.Nodup) (more : used.length < candidates.length) :
    (allocate used candidates).isSome = true := by
  cases chosen : allocate used candidates with
  | some value => rfl
  | none =>
    have every := List.find?_eq_none.mp chosen
    have contained : candidates ⊆ used := by
      intro item member
      have present := every item member
      simpa using present
    have bound := unique.length_le_of_subset contained
    omega

theorem allocation_preserves_unique_names (used candidates : List Nat) (name : Nat)
    (unique : used.Nodup) (chosen : allocate used candidates = some name) :
    (name :: used).Nodup :=
  List.nodup_cons.mpr ⟨allocated_is_fresh used candidates name chosen, unique⟩

structure Resource where
  name : Nat
  owner : Nat
  deriving Repr, DecidableEq

/-- References require the resource's owner, as well as its name. -/
def resolves (resources : List Resource) (reference : Resource) : Bool :=
  resources.contains reference

def closed (resources references : List Resource) : Bool :=
  references.all (resolves resources)

theorem closure_has_exact_target (resources references : List Resource)
    (valid : closed resources references = true) (reference : Resource)
    (member : reference ∈ references) : reference ∈ resources := by
  simpa [resolves] using (List.all_eq_true.mp valid) reference member

theorem unique_names_prevent_wrong_owner (resources : List Resource)
    (unique : (resources.map Resource.name).Nodup) (a b : Resource)
    (one : a ∈ resources) (two : b ∈ resources) (same : a.name = b.name) :
    a.owner = b.owner := by
  induction resources with
  | nil => simp at one
  | cons first rest induction =>
    obtain ⟨fresh, remaining⟩ := List.nodup_cons.mp unique
    rcases List.mem_cons.mp one with one | one
    · subst a
      rcases List.mem_cons.mp two with two | two
      · subst b; rfl
      · exact False.elim (fresh (List.mem_map.mpr ⟨b, two, same.symm⟩))
    · rcases List.mem_cons.mp two with two | two
      · subst b
        exact False.elim (fresh (List.mem_map.mpr ⟨a, one, same⟩))
      · exact induction remaining one two

/-- A folder occurrence, rather than fire identity, owns every repeated view's ring. -/
def ringTargets (folder count : Nat) : List (Nat × Nat) :=
  (List.range count).map (folder, ·)

def visibleThrough (step index : Nat) : Bool := decide (index ≤ step)

theorem reveal_never_hides_prior_rings (first second index : Nat)
    (forward : first ≤ second) (visible : visibleThrough first index = true) :
    visibleThrough second index = true := by
  simp only [visibleThrough, decide_eq_true_eq] at *
  omega

theorem final_step_reveals_every_target (count index : Nat) (inside : index < count) :
    visibleThrough (count - 1) index = true := by
  simp only [visibleThrough, decide_eq_true_eq]
  omega

theorem ring_targets_exact (folder count targetFolder index : Nat) :
    (targetFolder, index) ∈ ringTargets folder count ↔
      targetFolder = folder ∧ index < count := by
  simp only [ringTargets, List.mem_map, List.mem_range, Prod.mk.injEq]
  constructor
  · rintro ⟨item, inside, same, rfl⟩
    exact ⟨same.symm, inside⟩
  · rintro ⟨rfl, inside⟩
    exact ⟨index, inside, rfl, rfl⟩

theorem ring_targets_unique (folder count : Nat) :
    (ringTargets folder count).Nodup := by
  apply List.pairwise_map.mpr
  apply List.Pairwise.imp _ List.nodup_range
  intro first second different same
  exact different (Prod.mk.inj same).2

theorem different_folders_have_no_shared_targets (first second count other : Nat)
    (different : first ≠ second) (target : Nat × Nat)
    (one : target ∈ ringTargets first count) : target ∉ ringTargets second other := by
  intro two
  have a := (ring_targets_exact first count target.1 target.2).mp one
  have b := (ring_targets_exact second other target.1 target.2).mp two
  exact different (a.1.symm.trans b.1)

end PeriScribe.OutputReferences
