import Std

namespace PeriScribe.ComplexOwnership

/-- Unknown aggregate identifiers cannot collide with known grouped fire identities. -/
inductive Parent where
  | known : Nat → Parent
  | external : Nat → Parent
  deriving BEq, ReflBEq, LawfulBEq, DecidableEq, Repr

abbrev Aliases := Nat → Option Nat

def parentKey (aliases : Aliases) (identifier : Nat) : Parent :=
  match aliases identifier with
  | some fire => .known fire
  | none => .external identifier

/-- Contradictory declarations provide no defensible single owner. -/
def unique {α : Type} [BEq α] : List α → Option α
  | [] => none
  | first :: rest => if rest.all (· == first) then some first else none

theorem unique_iff {α : Type} [BEq α] [LawfulBEq α]
    (values : List α) (parent : α) :
    unique values = some parent ↔
      parent ∈ values ∧ ∀ other ∈ values, other = parent := by
  cases values with
  | nil => simp [unique]
  | cons first rest =>
    constructor
    · intro selected
      by_cases consistent : rest.all (· == first) = true
      · simp only [unique, consistent, ↓reduceIte,
          Option.some.injEq] at selected
        subst parent
        refine ⟨by simp, ?_⟩
        intro other present
        rcases List.mem_cons.mp present with same | member
        · exact same
        · exact beq_iff_eq.mp (List.all_eq_true.mp consistent other member)
      · simp [unique, consistent] at selected
    · rintro ⟨_, allSame⟩
      have firstSame := allSame first (by simp)
      have consistent : rest.all (· == first) = true := by
        apply List.all_eq_true.mpr
        intro other member
        exact beq_iff_eq.mpr ((allSame other (by simp [member])).trans firstSame.symm)
      simp only [unique, consistent, ↓reduceIte]
      exact congrArg some firstSame

theorem unique_ignores_order_and_duplicates {α : Type} [BEq α] [LawfulBEq α]
    (first second : List α)
    (sameMembers : ∀ value, value ∈ first ↔ value ∈ second) :
    unique first = unique second := by
  have same : ∀ value, unique first = some value ↔ unique second = some value := by
    intro value
    rw [unique_iff, unique_iff]
    constructor
    · rintro ⟨present, allSame⟩
      exact ⟨(sameMembers value).mp present,
        fun other member => allSame other ((sameMembers other).mpr member)⟩
    · rintro ⟨present, allSame⟩
      exact ⟨(sameMembers value).mpr present,
        fun other member => allSame other ((sameMembers other).mp member)⟩
  cases one : unique first <;> cases two : unique second
  · rfl
  · exact False.elim (by simpa [one] using (same _).mpr two)
  · exact False.elim (by simpa [two] using (same _).mp one)
  · exact ((same _).mp one).symm.trans two

theorem parent_aliases_have_one_key (aliases : Aliases) (first second parent : Nat)
    (one : aliases first = some parent) (two : aliases second = some parent) :
    parentKey aliases first = parentKey aliases second := by
  simp [parentKey, one, two]

/-- Incident modification time outranks feed priority and within-feed serial ties. -/
structure Observation where
  child : Nat
  parent : Option Nat
  time : Nat
  priority : Nat
  serial : Nat
  deriving BEq, ReflBEq, LawfulBEq, DecidableEq, Repr

def noLater (first second : Observation) : Prop :=
  first.time < second.time ∨ first.time = second.time ∧
    (first.priority < second.priority ∨ first.priority = second.priority ∧
      first.serial ≤ second.serial)

instance (first second : Observation) : Decidable (noLater first second) :=
  inferInstanceAs (Decidable (_ ∨ _ ∧ (_ ∨ _ ∧ _)))

def latest (aliases : Aliases) (observations : List Observation) (child : Nat) :=
  observations.filter (fun observation =>
    aliases observation.child == some child && observations.all (fun other =>
      aliases other.child != some child || decide (noLater other observation)))

def currentChoices (aliases : Aliases) (observations : List Observation)
    (child : Nat) :=
  (latest aliases observations child).map (fun observation =>
    observation.parent.map (parentKey aliases))

inductive Assignment where
  | unobserved
  | released
  | ambiguous
  | assigned : Parent → Assignment
  deriving BEq, ReflBEq, LawfulBEq, DecidableEq, Repr

def direct (aliases : Aliases) (observations : List Observation) (child : Nat) :=
  let choices := currentChoices aliases observations child
  if choices.isEmpty then Assignment.unobserved
  else match unique choices with
  | none => .ambiguous
  | some none => .released
  | some (some parent) => .assigned parent

/-- Visited identities prevent a malformed merger cycle from inventing an owner. -/
def follow (aliases : Aliases) (observations : List Observation) :
    Nat → List Nat → Parent → Option Parent
  | 0, _, _ => none
  | _ + 1, _, .external identifier => some (.external identifier)
  | fuel + 1, seen, .known fire =>
    if seen.contains fire then none
    else match direct aliases observations fire with
    | .unobserved | .released => some (.known fire)
    | .ambiguous => none
    | .assigned parent => follow aliases observations fuel (fire :: seen) parent

def currentOwner (aliases : Aliases) (observations : List Observation)
    (fuel child : Nat) :=
  match direct aliases observations child with
  | .assigned parent => follow aliases observations fuel [child] parent
  | _ => none

def historicalParents (aliases : Aliases) (observations : List Observation) :=
  observations.filterMap (fun observation =>
    if (aliases observation.child).isSome then
      observation.parent.map (parentKey aliases)
    else none)

def currentMembers (aliases : Aliases) (observations : List Observation)
    (fires : List Nat) (parent : Parent) :=
  fires.filter (fun child =>
    currentOwner aliases observations (fires.length + 1) child == some parent)

def currentVisible (aliases : Aliases) (observations : List Observation)
    (fires : List Nat) :=
  fires.filter (fun fire => !(historicalParents aliases observations).contains
    (.known fire))

theorem latest_has_maximal_clock (aliases : Aliases) (observations : List Observation)
    (child : Nat) (observation : Observation) :
    observation ∈ latest aliases observations child ↔
      observation ∈ observations ∧ aliases observation.child = some child ∧
        ∀ other ∈ observations, aliases other.child = some child →
          noLater other observation := by
  simp only [latest, List.mem_filter, Bool.and_eq_true, beq_iff_eq,
    List.all_eq_true, Bool.or_eq_true, bne_iff_ne, decide_eq_true_eq]
  constructor
  · rintro ⟨member, owned, clocks⟩
    exact ⟨member, owned, fun other present same =>
      (clocks other present).resolve_left (fun different => different same)⟩
  · rintro ⟨member, owned, clocks⟩
    refine ⟨member, owned, ?_⟩
    intro other present
    by_cases same : aliases other.child = some child
    · exact Or.inr (clocks other present same)
    · exact Or.inl same

theorem strict_newer_observation_displaces_old (aliases : Aliases)
    (observations : List Observation) (child : Nat) (old newer : Observation)
    (present : newer ∈ observations) (owned : aliases newer.child = some child)
    (newerTime : old.time < newer.time) :
    old ∉ latest aliases observations child := by
  intro retained
  have clock := ((latest_has_maximal_clock _ _ _ _).mp retained).2.2 newer present owned
  simp only [noLater] at clock
  omega

theorem direct_assignment_has_latest_source (aliases : Aliases)
    (observations : List Observation) (child : Nat) (parent : Parent)
    (chosen : direct aliases observations child = .assigned parent) :
    ∃ observation ∈ latest aliases observations child,
      observation.parent.map (parentKey aliases) = some parent := by
  simp only [direct] at chosen
  split at chosen
  · contradiction
  · cases selected : unique (currentChoices aliases observations child) with
    | none => simp [selected] at chosen
    | some result =>
      cases result with
      | none => simp [selected] at chosen
      | some found =>
        simp only [selected, Assignment.assigned.injEq] at chosen
        subst found
        exact List.mem_map.mp ((unique_iff _ _).mp selected).1

theorem latest_release_removes_current_owner (aliases : Aliases)
    (observations : List Observation) (fuel child : Nat)
    (present : none ∈ currentChoices aliases observations child)
    (agree : ∀ choice ∈ currentChoices aliases observations child, choice = none) :
    currentOwner aliases observations fuel child = none := by
  have chosen : unique (currentChoices aliases observations child) = some none :=
    (unique_iff _ _).mpr ⟨present, agree⟩
  have nonempty : (currentChoices aliases observations child).isEmpty = false := by
    cases choices : currentChoices aliases observations child with
    | nil => simp [choices] at present
    | cons => rfl
  simp [currentOwner, direct, nonempty, chosen]

theorem release_removes_current_owner (aliases : Aliases)
    (observations : List Observation) (fuel child : Nat)
    (released : direct aliases observations child = .released) :
    currentOwner aliases observations fuel child = none := by
  simp [currentOwner, released]

theorem merger_follows_parent (aliases : Aliases) (observations : List Observation)
    (fuel child parent : Nat) (next : Parent)
    (first : direct aliases observations child = .assigned (.known parent))
    (second : direct aliases observations parent = .assigned next)
    (different : child ≠ parent) :
    currentOwner aliases observations (fuel + 1) child =
      follow aliases observations fuel [parent, child] next := by
  simp [currentOwner, first, follow, second, Ne.symm different]

theorem visited_cycle_has_no_owner (aliases : Aliases)
    (observations : List Observation) (fuel : Nat) (seen : List Nat) (fire : Nat)
    (cycle : fire ∈ seen) :
    follow aliases observations fuel seen (.known fire) = none := by
  cases fuel <;> simp [follow, cycle]

theorem current_membership_is_reciprocal (aliases : Aliases)
    (observations : List Observation) (fires : List Nat)
    (parent : Parent) (child : Nat) :
    child ∈ currentMembers aliases observations fires parent ↔
      child ∈ fires ∧ currentOwner aliases observations (fires.length + 1) child =
        some parent := by
  simp [currentMembers]

theorem current_ownership_is_exclusive (aliases : Aliases)
    (observations : List Observation) (fires : List Nat) (first second : Parent)
    (child : Nat) (one : child ∈ currentMembers aliases observations fires first)
    (two : child ∈ currentMembers aliases observations fires second) :
    first = second := by
  have a := (current_membership_is_reciprocal _ _ _ _ _).mp one
  have b := (current_membership_is_reciprocal _ _ _ _ _).mp two
  exact Option.some.inj (a.2.symm.trans b.2)

theorem temporal_visibility_preserves_components (aliases : Aliases)
    (observations : List Observation) (fires : List Nat) (fire : Nat) :
    fire ∈ currentVisible aliases observations fires ↔
      fire ∈ fires ∧ Parent.known fire ∉ historicalParents aliases observations := by
  simp [currentVisible]


theorem latest_ignores_order_and_duplicates (aliases : Aliases)
    (first second : List Observation)
    (same : ∀ observation, observation ∈ first ↔ observation ∈ second)
    (child : Nat) (observation : Observation) :
    observation ∈ latest aliases first child ↔
      observation ∈ latest aliases second child := by
  rw [latest_has_maximal_clock, latest_has_maximal_clock]
  constructor
  · rintro ⟨present, owned, clocks⟩
    exact ⟨(same _).mp present, owned,
      fun other member found => clocks other ((same other).mpr member) found⟩
  · rintro ⟨present, owned, clocks⟩
    exact ⟨(same _).mpr present, owned,
      fun other member found => clocks other ((same other).mp member) found⟩

theorem direct_ignores_order_and_duplicates (aliases : Aliases)
    (first second : List Observation)
    (same : ∀ observation, observation ∈ first ↔ observation ∈ second)
    (child : Nat) : direct aliases first child = direct aliases second child := by
  have choices : ∀ parent, parent ∈ currentChoices aliases first child ↔
      parent ∈ currentChoices aliases second child := by
    intro parent
    simp only [currentChoices, List.mem_map]
    constructor
    · rintro ⟨observation, member, found⟩
      exact ⟨observation,
        (latest_ignores_order_and_duplicates _ _ _ same _ _).mp member, found⟩
    · rintro ⟨observation, member, found⟩
      exact ⟨observation,
        (latest_ignores_order_and_duplicates _ _ _ same _ _).mpr member, found⟩
  have empty : (currentChoices aliases first child).isEmpty =
      (currentChoices aliases second child).isEmpty := by
    apply Bool.eq_iff_iff.mpr
    simp only [List.isEmpty_iff, List.eq_nil_iff_forall_not_mem]
    exact ⟨fun absent parent present => absent parent ((choices parent).mpr present),
      fun absent parent present => absent parent ((choices parent).mp present)⟩
  simp only [direct, empty, unique_ignores_order_and_duplicates _ _ choices]

theorem follow_ignores_order_and_duplicates (aliases : Aliases)
    (first second : List Observation)
    (same : ∀ observation, observation ∈ first ↔ observation ∈ second)
    (fuel : Nat) (seen : List Nat) (parent : Parent) :
    follow aliases first fuel seen parent = follow aliases second fuel seen parent := by
  induction fuel generalizing seen parent with
  | zero => rfl
  | succ fuel induction =>
    cases parent with
    | external => rfl
    | known fire =>
      simp only [follow, direct_ignores_order_and_duplicates _ _ _ same]
      split
      · rfl
      · split <;> try rfl
        exact induction _ _

theorem current_ownership_ignores_order_and_duplicates (aliases : Aliases)
    (first second : List Observation)
    (same : ∀ observation, observation ∈ first ↔ observation ∈ second)
    (fuel child : Nat) :
    currentOwner aliases first fuel child = currentOwner aliases second fuel child := by
  simp only [currentOwner, direct_ignores_order_and_duplicates _ _ _ same]
  split <;> try rfl
  exact follow_ignores_order_and_duplicates _ _ _ same _ _ _

theorem following_stops_at_a_root (aliases : Aliases) (observations : List Observation)
    (fuel : Nat) (seen : List Nat) (parent root : Parent)
    (found : follow aliases observations fuel seen parent = some root) :
    ∃ identifier, root = .external identifier ∨
      root = .known identifier ∧ (direct aliases observations identifier = .unobserved ∨
        direct aliases observations identifier = .released) := by
  induction fuel generalizing seen parent with
  | zero => simp [follow] at found
  | succ fuel induction =>
    cases parent with
    | external identifier =>
      simp only [follow, Option.some.injEq] at found
      exact ⟨identifier, Or.inl found.symm⟩
    | known fire =>
      simp only [follow] at found
      split at found
      · contradiction
      · split at found
        · simp only [Option.some.injEq] at found
          exact ⟨fire, Or.inr ⟨found.symm, Or.inl (by assumption)⟩⟩
        · simp only [Option.some.injEq] at found
          exact ⟨fire, Or.inr ⟨found.symm, Or.inr (by assumption)⟩⟩
        · contradiction
        · exact induction _ _ found

end PeriScribe.ComplexOwnership
