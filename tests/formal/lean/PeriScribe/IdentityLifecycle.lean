import PeriScribe.Identity

namespace PeriScribe.IdentityLifecycle

abbrev Assignments := Nat → Option Nat

def Unique (owned : Assignments) : Prop :=
  ∀ first second key, owned first = some key → owned second = some key → first = second

def Covered (owned : Assignments) (reserved : List Nat) : Prop :=
  ∀ fire key, owned fire = some key → key ∈ reserved

/-- An adoption phase sees all competing claimants before any assignment is applied. -/
def adopt (owned : Assignments) (seeking : List Nat) (options : Nat → List Nat) :
    Assignments := fun fire =>
  match owned fire with
  | some key => some key
  | none => if fire ∈ seeking then Identity.uniqueOwner seeking options fire else none

def adoptedKeys (seeking : List Nat) (options : Nat → List Nat) : List Nat :=
  seeking.filterMap (Identity.uniqueOwner seeking options)

theorem adoption_retains_known (owned : Assignments) (seeking : List Nat)
    (options : Nat → List Nat) (fire key : Nat) (known : owned fire = some key) :
    adopt owned seeking options fire = some key := by simp [adopt, known]

theorem adoption_has_source (owned : Assignments) (seeking : List Nat)
    (options : Nat → List Nat) (fire key : Nat)
    (selected : adopt owned seeking options fire = some key) :
    owned fire = some key ∨
      (owned fire = none ∧ fire ∈ seeking ∧
        Identity.uniqueOwner seeking options fire = some key) := by
  unfold adopt at selected
  cases known : owned fire with
  | some previous => left; simp [known] at selected; simp [selected]
  | none =>
    right
    simp only [known] at selected
    split at selected
    · exact ⟨rfl, by assumption, selected⟩
    · contradiction

theorem adoption_preserves_unique (owned : Assignments) (seeking reserved : List Nat)
    (options : Nat → List Nat) (unique : Unique owned) (covered : Covered owned
        reserved)
    (unreserved : ∀ fire ∈ seeking, ∀ key ∈ options fire, key ∉ reserved) :
    Unique (adopt owned seeking options) := by
  intro first second key firstOwner secondOwner
  rcases adoption_has_source owned seeking options first key firstOwner with old | fresh
  · rcases adoption_has_source owned seeking options second key secondOwner with oldTwo
      |
      freshTwo
    · exact unique first second key old oldTwo
    · have singleton := (Identity.unique_owner_has_one_candidate seeking options
        second key freshTwo.2.2).1
      exact False.elim (unreserved second freshTwo.2.1 key (by simp [singleton])
        (covered first key old))
  · rcases adoption_has_source owned seeking options second key secondOwner with oldTwo
      |
      freshTwo
    · have singleton := (Identity.unique_owner_has_one_candidate seeking options
        first key fresh.2.2).1
      exact False.elim (unreserved first fresh.2.1 key (by simp [singleton])
        (covered second key oldTwo))
    · exact Identity.adopted_histories_have_only_one_owner seeking options first second
        key freshTwo.2.1 fresh.2.2 freshTwo.2.2

theorem adoption_extends_reservations (owned : Assignments) (seeking reserved : List
    Nat)
    (options : Nat → List Nat) (covered : Covered owned reserved) :
    Covered (adopt owned seeking options) (reserved ++ adoptedKeys seeking options) :=
        by
  intro fire key selected
  rcases adoption_has_source owned seeking options fire key selected with old | fresh
  · exact List.mem_append_left _ (covered fire key old)
  · apply List.mem_append_right
    exact List.mem_filterMap.mpr ⟨fire, fresh.2.1, fresh.2.2⟩

def setOwner (owned : Assignments) (fire key : Nat) : Assignments :=
  fun current => if current = fire then some key else owned current

theorem fresh_assignment_preserves_unique (owned : Assignments) (reserved : List Nat)
    (fire key : Nat) (unique : Unique owned) (covered : Covered owned reserved)
    (fresh : key ∉ reserved) : Unique (setOwner owned fire key) := by
  intro first second value firstOwner secondOwner
  unfold setOwner at firstOwner secondOwner
  split at firstOwner <;> split at secondOwner
  · omega
  · have equal : key = value := Option.some.inj firstOwner
    subst value
    exact False.elim (fresh (covered second key secondOwner))
  · have equal : key = value := Option.some.inj secondOwner
    subst value
    exact False.elim (fresh (covered first key firstOwner))
  · exact unique first second value firstOwner secondOwner

theorem fresh_assignment_extends_reservations (owned : Assignments)
    (reserved : List Nat) (fire key : Nat) (covered : Covered owned reserved) :
    Covered (setOwner owned fire key) (key :: reserved) := by
  intro current value selected
  unfold setOwner at selected
  split at selected
  · simp_all
  · exact List.mem_cons_of_mem key (covered current value selected)

/-- The allocator's only ownership assumption is freshness against every reserved key.
    -/
def allocate (fresh : Nat → List Nat → Nat) : List Nat → Assignments → List Nat →
    Assignments
  | [], owned, _ => owned
  | fire :: rest, owned, reserved =>
    match owned fire with
    | some _ => allocate fresh rest owned reserved
    | none =>
      let key := fresh fire reserved
      allocate fresh rest (setOwner owned fire key) (key :: reserved)

theorem allocation_preserves_unique (fresh : Nat → List Nat → Nat)
    (freshness : ∀ fire reserved, fresh fire reserved ∉ reserved)
    (fires : List Nat) (owned : Assignments) (reserved : List Nat)
    (unique : Unique owned) (covered : Covered owned reserved) :
    Unique (allocate fresh fires owned reserved) := by
  induction fires generalizing owned reserved with
  | nil => exact unique
  | cons fire rest induction =>
    unfold allocate
    split
    · exact induction owned reserved unique covered
    · exact induction _ _
        (fresh_assignment_preserves_unique owned reserved fire (fresh fire reserved)
          unique covered (freshness fire reserved))
        (fresh_assignment_extends_reservations owned reserved fire _ covered)

theorem allocation_retains_known (fresh : Nat → List Nat → Nat)
    (fires : List Nat) (owned : Assignments) (reserved : List Nat) (fire key : Nat)
    (known : owned fire = some key) :
    allocate fresh fires owned reserved fire = some key := by
  induction fires generalizing owned reserved with
  | nil => exact known
  | cons current rest induction =>
    unfold allocate
    cases currentKnown : owned current with
    | some previous => exact induction _ _ known
    | none =>
      apply induction
      have different : fire ≠ current := by intro same; subst current; simp_all
      simp [setOwner, different, known]

theorem allocation_is_total (fresh : Nat → List Nat → Nat) (fires : List Nat)
    (owned : Assignments) (reserved : List Nat) (fire : Nat) (present : fire ∈ fires) :
    ∃ key, allocate fresh fires owned reserved fire = some key := by
  induction fires generalizing owned reserved with
  | nil => simp at present
  | cons current rest induction =>
    unfold allocate
    cases known : owned current with
    | some key =>
      simp only
      rcases List.mem_cons.mp present with same | member
      · subst current; exact ⟨key, allocation_retains_known fresh rest owned reserved
          fire key known⟩
      · exact induction owned reserved member
    | none =>
      simp only
      rcases List.mem_cons.mp present with same | member
      · subst current
        exact ⟨fresh fire reserved, allocation_retains_known fresh rest _ _ fire _
          (by simp [setOwner])⟩
      · exact induction _ _ member

/-- Opaque local identities occupy a namespace above every serialized fixture key. -/
def freshKey (base requested : Nat) (nameCollision : Bool) (reserved : List Nat) : Nat
    :=
  if requested ∉ reserved ∧ !nameCollision then requested else base + reserved.sum + 1

theorem member_bounded_by_sum (values : List Nat) (value : Nat) (present : value ∈
    values) :
    value ≤ values.sum := by
  induction values with
  | nil => simp at present
  | cons head tail induction =>
    simp only [List.sum_cons]
    rcases List.mem_cons.mp present with same | member
    · omega
    · have bound := induction member; omega

theorem fresh_key_is_unused (base requested : Nat) (nameCollision : Bool)
    (reserved : List Nat) : freshKey base requested nameCollision reserved ∉ reserved
        := by
  unfold freshKey
  split
  · simp_all
  · intro present
    have bound := member_bounded_by_sum reserved _ present
    omega

/-- Name-only claimants finish before identified claimants see the remaining histories.
    -/
def resolve (fresh : Nat → List Nat → Nat) (fires unnamed identified : List Nat)
    (known : Assignments) (reserved historical : List Nat)
    (options : List Nat → Nat → List Nat) : Assignments :=
  let firstOptions := options reserved
  let first := adopt known unnamed firstOptions
  let secondReserved := reserved ++ adoptedKeys unnamed firstOptions
  let secondOptions := options secondReserved
  let second := adopt first identified secondOptions
  allocate fresh fires second
    (historical ++ secondReserved ++ adoptedKeys identified secondOptions)

theorem complete_resolver_has_unique_owners (fresh : Nat → List Nat → Nat)
    (freshness : ∀ fire reserved, fresh fire reserved ∉ reserved)
    (fires unnamed identified : List Nat) (known : Assignments) (reserved historical :
        List Nat)
    (options : List Nat → Nat → List Nat) (unique : Unique known)
    (covered : Covered known reserved)
    (unreserved : ∀ reserved fire key, key ∈ options reserved fire → key ∉ reserved) :
    Unique (resolve fresh fires unnamed identified known reserved historical options)
        := by
  unfold resolve
  apply allocation_preserves_unique fresh freshness
  · apply adoption_preserves_unique
    · exact adoption_preserves_unique known unnamed reserved _ unique covered
        (fun fire _ key member => unreserved reserved fire key member)
    · exact adoption_extends_reservations known unnamed reserved _ covered
    · intro fire _ key member; exact unreserved _ fire key member
  · intro fire key selected
    have present := adoption_extends_reservations _ identified
      (reserved ++ adoptedKeys unnamed (options reserved)) _
      (adoption_extends_reservations known unnamed reserved _ covered) fire key selected
    simpa [List.append_assoc] using List.mem_append_right historical present

theorem complete_resolver_preserves_identifier_owner (fresh : Nat → List Nat → Nat)
    (fires unnamed identified : List Nat) (known : Assignments) (reserved historical :
        List Nat)
    (options : List Nat → Nat → List Nat) (fire key : Nat)
    (previous : known fire = some key) :
    resolve fresh fires unnamed identified known reserved historical options fire =
        some key := by
  apply allocation_retains_known
  apply adoption_retains_known
  exact adoption_retains_known known unnamed _ fire key previous

theorem complete_resolver_assigns_every_fire (fresh : Nat → List Nat → Nat)
    (fires unnamed identified : List Nat) (known : Assignments) (reserved historical :
        List Nat)
    (options : List Nat → Nat → List Nat) (fire : Nat) (present : fire ∈ fires) :
    ∃ key, resolve fresh fires unnamed identified known reserved historical options
        fire = some key :=
  allocation_is_total fresh fires _ _ fire present

def choices (histories : List Identity.History) (current : Nat → Option Identity.Fire)
    (reserved : List Nat) (fire : Nat) : List Nat :=
  match current fire with
  | none => []
  | some evidence => Identity.candidates histories reserved evidence

theorem choices_exclude_reserved (histories : List Identity.History)
    (current : Nat → Option Identity.Fire) (reserved : List Nat) (fire key : Nat)
    (selected : key ∈ choices histories current reserved fire) : key ∉ reserved := by
  unfold choices at selected
  split at selected
  · simp at selected
  · exact Identity.reserved_histories_cannot_be_adopted histories reserved _ key
      selected

theorem complete_candidate_resolver_unique (fresh : Nat → List Nat → Nat)
    (freshness : ∀ fire reserved, fresh fire reserved ∉ reserved)
    (fires unnamed identified : List Nat) (known : Assignments)
    (reserved historical : List Nat) (histories : List Identity.History)
    (current : Nat → Option Identity.Fire) (unique : Unique known)
    (covered : Covered known reserved) :
    Unique (resolve fresh fires unnamed identified known reserved historical
      (choices histories current)) :=
  complete_resolver_has_unique_owners fresh freshness fires unnamed identified known
    reserved historical _ unique covered (choices_exclude_reserved histories current)

theorem first_adoption_phase_keeps_priority (fresh : Nat → List Nat → Nat)
    (fires unnamed identified : List Nat) (known : Assignments)
    (reserved historical : List Nat) (options : List Nat → Nat → List Nat)
    (fire key : Nat) (adopted : adopt known unnamed (options reserved) fire = some key)
        :
    resolve fresh fires unnamed identified known reserved historical options fire =
      some key := by
  apply allocation_retains_known
  exact adoption_retains_known _ identified _ fire key adopted

/-- Checkpoints accumulate acknowledged evidence without erasing absent histories. -/
def acknowledge (previous : Nat → List Nat) (current : Nat → List Nat) : Nat → List Nat
    :=
  fun key => previous key ++ current key

def persist : List (Nat → List Nat) → (Nat → List Nat) → (Nat → List Nat)
  | [], previous => previous
  | current :: rest, previous => persist rest (acknowledge previous current)

/-- A publication emits a history record exactly when it adds perimeter evidence. -/
def novel (previous current : List Nat) : Bool :=
  current.any (fun evidence => evidence ∉ previous)

theorem novel_iff_new_evidence (previous current : List Nat) :
    novel previous current = true ↔
      ∃ evidence ∈ current, evidence ∉ previous := by
  simp [novel]

theorem novel_iff_acknowledgement_grows (previous current : Nat → List Nat)
    (key : Nat) :
    novel (previous key) (current key) = true ↔
      ∃ evidence, evidence ∈ acknowledge previous current key ∧
        evidence ∉ previous key := by
  simp only [novel_iff_new_evidence, acknowledge, List.mem_append]
  constructor
  · rintro ⟨evidence, member, missing⟩
    exact ⟨evidence, Or.inr member, missing⟩
  · rintro ⟨evidence, member | member, missing⟩
    · exact False.elim (missing member)
    · exact ⟨evidence, member, missing⟩

theorem acknowledgement_preserves_history (previous current : Nat → List Nat)
    (key evidence : Nat) (known : evidence ∈ previous key) :
    evidence ∈ acknowledge previous current key := List.mem_append_left _ known

theorem acknowledgement_has_support (previous current : Nat → List Nat)
    (key evidence : Nat) : evidence ∈ acknowledge previous current key ↔
      evidence ∈ previous key ∨ evidence ∈ current key := List.mem_append

theorem every_publication_preserves_history (publications : List (Nat → List Nat))
    (previous : Nat → List Nat) (key evidence : Nat) (known : evidence ∈ previous key) :
    evidence ∈ persist publications previous key := by
  induction publications generalizing previous with
  | nil => exact known
  | cons current rest induction =>
    exact induction _ (acknowledgement_preserves_history previous current key evidence
      known)

/-- New aliases override only the declared alias; all other bindings remain retained. -/
def saveAliases (previous current : Assignments) : Assignments :=
  fun alias => (current alias).or (previous alias)

def publishAliases : List Assignments → Assignments → Assignments
  | [], previous => previous
  | current :: rest, previous => publishAliases rest (saveAliases previous current)

theorem alias_update_has_source (previous current : Assignments) (alias key : Nat)
    (selected : saveAliases previous current alias = some key) :
    current alias = some key ∨ (current alias = none ∧ previous alias = some key) := by
  cases changed : current alias <;> simp_all [saveAliases]

theorem consistent_alias_survives_publication (previous current : Assignments)
    (alias key : Nat) (known : previous alias = some key)
    (consistent : current alias = none ∨ current alias = some key) :
    saveAliases previous current alias = some key := by
  rcases consistent with absent | same <;> simp_all [saveAliases]

theorem consistent_alias_survives_every_publication (publications : List Assignments)
    (previous : Assignments) (alias key : Nat) (known : previous alias = some key)
    (consistent : ∀ current ∈ publications,
      current alias = none ∨ current alias = some key) :
    publishAliases publications previous alias = some key := by
  induction publications generalizing previous with
  | nil => exact known
  | cons current rest induction =>
    apply induction
    · exact consistent_alias_survives_publication previous current alias key known
        (consistent current (by simp))
    · intro update member; exact consistent update (by simp [member])

theorem stable_identifiers_agree (identifiers : List Nat) (aliases : Assignments)
    (key : Nat)
    (consistent : ∀ alias ∈ identifiers, aliases alias = none ∨ aliases alias = some
        key)
    (available : ∃ alias ∈ identifiers, aliases alias = some key) :
    Identity.stable identifiers aliases = some key := by
  induction identifiers with
  | nil => simp at available
  | cons first rest induction =>
    rcases consistent first (by simp) with missing | known
    · simp only [Identity.stable, missing]
      apply induction
      · intro alias member; exact consistent alias (by simp [member])
      · obtain ⟨alias, member, known⟩ := available
        refine ⟨alias, ?_, known⟩
        rcases List.mem_cons.mp member with same | member
        · subst alias; simp [missing] at known
        · exact member
    · simp [Identity.stable, known]

theorem repeated_acknowledgement_is_idempotent (previous current : Nat → List Nat)
    (key evidence : Nat) :
    evidence ∈ acknowledge (acknowledge previous current) current key ↔
      evidence ∈ acknowledge previous current key := by
  simp [acknowledge]

end PeriScribe.IdentityLifecycle
