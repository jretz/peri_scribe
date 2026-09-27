import Std

namespace PeriScribe.Identity

structure History where
  key : Nat
  names : List Nat
  signatures : List Nat
  sources : List Nat
  localAliases : List Nat
  deriving Repr

structure Fire where
  key : Nat
  name : Nat
  signatures : List Nat
  sources : List Nat
  preferred : Option Nat
  deriving Repr

/-- Source continuity can survive a corrected perimeter with a different signature. -/
def eligible (reserved : List Nat) (fire : Fire) (history : History) : Bool :=
  !reserved.contains history.key && history.names.contains fire.name &&
    (history.signatures.isEmpty ||
      fire.signatures.any history.signatures.contains ||
      fire.sources.any history.sources.contains)

/-- Acknowledged local aliases settle ambiguity only inside eligible histories. -/
def prefer (base preferredKeys : List Nat) (preferred : Option Nat) : List Nat :=
  match preferred with
  | some key => if key ∈ preferredKeys then [key]
      else if preferredKeys.length = 1 then preferredKeys else base
  | none => if preferredKeys.length = 1 then preferredKeys else base

def candidates (histories : List History) (reserved : List Nat)
    (fire : Fire) : List Nat :=
  let eligibleHistories := histories.filter (eligible reserved fire)
  let base := eligibleHistories.map History.key
  let preferredKeys := (eligibleHistories.filter
    (fun history => history.localAliases.contains fire.name)).map History.key
  prefer base preferredKeys fire.preferred

/-- A singleton candidate is usable only when no other fire can claim it. -/
def uniqueOwner (fires : List Nat) (options : Nat → List Nat)
    (fire : Nat) : Option Nat :=
  match options fire with
  | [key] => if fires.all (fun other => other == fire || !(options other).contains key)
      then some key else none
  | _ => none

theorem prefer_never_invents_candidate (base preferredKeys : List Nat)
    (preferred : Option Nat)
    (included : ∀ key ∈ preferredKeys, key ∈ base) (key : Nat)
    (member : key ∈ prefer base preferredKeys preferred) : key ∈ base := by
  cases preferred with
  | none =>
    simp only [prefer] at member
    split at member
    · exact included key member
    · exact member
  | some wanted =>
    simp only [prefer] at member
    split at member
    · simp only [List.mem_singleton] at member
      subst key
      exact included wanted (by assumption)
    · split at member
      · exact included key member
      · exact member

theorem candidates_have_continuity (histories : List History) (reserved : List Nat)
    (fire : Fire) (key : Nat) (member : key ∈ candidates histories reserved fire) :
    ∃ history ∈ histories,
      history.key = key ∧ eligible reserved fire history = true := by
  have localIncluded : ∀ key ∈
      ((histories.filter (eligible reserved fire)).filter
        (fun history => history.localAliases.contains fire.name)).map
        History.key,
      key ∈ (histories.filter (eligible reserved fire)).map History.key := by
    intro key present
    rcases List.mem_map.mp present with ⟨history, present, equal⟩
    exact List.mem_map.mpr ⟨history, (List.mem_filter.mp present).1, equal⟩
  have base := prefer_never_invents_candidate _ _ fire.preferred
    localIncluded key member
  rcases List.mem_map.mp base with ⟨history, present, equal⟩
  exact ⟨history, (List.mem_filter.mp present).1, equal, (List.mem_filter.mp present).2⟩

theorem reserved_histories_cannot_be_adopted (histories : List History)
    (reserved : List Nat) (fire : Fire) (key : Nat)
    (member : key ∈ candidates histories reserved fire) : key ∉ reserved := by
  rcases candidates_have_continuity histories reserved fire key member with
    ⟨history, _, same, valid⟩
  simp only [eligible, Bool.and_eq_true, Bool.not_eq_true']
    at valid
  simpa [same] using valid.1.1

theorem unique_owner_has_one_candidate (fires : List Nat) (options : Nat → List Nat)
    (fire key : Nat) (owned : uniqueOwner fires options fire = some key) :
    options fire = [key] ∧ ∀ other ∈ fires, other ≠ fire → key ∉ options other := by
  unfold uniqueOwner at owned
  split at owned
  next candidate shape =>
    split at owned
    next sole =>
      have same : candidate = key := Option.some.inj owned
      subst candidate
      refine ⟨shape, ?_⟩
      intro other member different
      have allowed := List.all_eq_true.mp sole other member
      simpa [different] using allowed
    next => contradiction
  next => contradiction

theorem adopted_histories_have_only_one_owner (fires : List Nat)
    (options : Nat → List Nat) (first second key : Nat)
    (secondPresent : second ∈ fires)
    (firstOwner : uniqueOwner fires options first = some key)
    (secondOwner : uniqueOwner fires options second = some key) : first = second := by
  have firstRule := unique_owner_has_one_candidate fires options first key firstOwner
  have secondRule := unique_owner_has_one_candidate fires options second key secondOwner
  by_cases same : first = second
  · exact same
  · have forbidden := firstRule.2 second secondPresent (Ne.symm same)
    simp [secondRule.1] at forbidden

/-- Sorted identifiers choose the first known association, irrespective of fire name. -/
def stable : List Nat → (Nat → Option Nat) → Option Nat
  | [], _ => none
  | identifier :: rest, aliases =>
    match aliases identifier with
    | some key => some key
    | none => stable rest aliases

theorem renamed_identified_fire_retains_history (identifiers : List Nat)
    (aliases : Nat → Option Nat) (identifier key : Nat)
    (known : aliases identifier = some key) :
    stable (identifier :: identifiers) aliases = some key := by simp [stable, known]

/-- The resolution priority prevents a name match from replacing a known identifier. -/
def resolve (known adopted : Option Nat) (fresh : Nat) : Nat :=
  known.getD (adopted.getD fresh)

theorem known_identifier_keeps_ownership (key fresh : Nat) (adopted : Option Nat) :
    resolve (some key) adopted fresh = key := rfl

end PeriScribe.Identity
