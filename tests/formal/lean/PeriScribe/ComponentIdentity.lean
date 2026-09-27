import Std

namespace PeriScribe.ComponentIdentity

/-- Tokens identify immutable source-row occurrences, ordered canonically. -/
def anchor : List Nat → Option Nat
  | [] => none
  | first :: rest => some (min first ((anchor rest).getD first))

theorem anchor_none_iff (rows : List Nat) : anchor rows = none ↔ rows = [] := by
  cases rows <;> simp [anchor]

theorem anchor_member (rows : List Nat) (value : Nat)
    (selected : anchor rows = some value) : value ∈ rows := by
  induction rows generalizing value with
  | nil => simp [anchor] at selected
  | cons first rest ih =>
    cases tail : anchor rest with
    | none =>
      have same : value = first := by simpa [anchor, tail] using selected.symm
      simp [same]
    | some next =>
      have same : min first next = value := by simpa [anchor, tail] using selected
      by_cases order : first ≤ next
      · simp [← same, Nat.min_eq_left order]
      · simp only [← same, Nat.min_eq_right (Nat.le_of_not_ge order), List.mem_cons]
        exact Or.inr (ih next tail)

theorem anchor_le_member (rows : List Nat) (value member : Nat)
    (selected : anchor rows = some value) (present : member ∈ rows) :
    value ≤ member := by
  induction rows generalizing value with
  | nil => simp at present
  | cons first rest ih =>
    cases tail : anchor rest with
    | none =>
      have empty := (anchor_none_iff rest).mp tail
      subst rest
      simp only [List.mem_cons, List.not_mem_nil, or_false] at present
      have same : first = value := by simpa [anchor] using selected
      omega
    | some next =>
      have same : min first next = value := by simpa [anchor, tail] using selected
      rcases List.mem_cons.mp present with rfl | inRest
      · rw [← same]; exact Nat.min_le_left _ _
      · rw [← same]
        exact Nat.le_trans (Nat.min_le_right first next) (ih next tail inRest)

theorem anchor_unique (rows : List Nat) (value : Nat) (present : value ∈ rows)
    (least : ∀ member ∈ rows, value ≤ member) : anchor rows = some value := by
  cases selected : anchor rows with
  | none => simp [(anchor_none_iff rows).mp selected] at present
  | some found =>
    have foundPresent := anchor_member rows found selected
    have low := anchor_le_member rows found value selected present
    have high := least found foundPresent
    have same : found = value := Nat.le_antisymm low high
    simp [same]

theorem anchor_permutation (first second : List Nat) (same : first.Perm second) :
    anchor first = anchor second := by
  cases selected : anchor first with
  | none =>
    have empty := (anchor_none_iff first).mp selected
    subst first
    have empty := List.Perm.nil_eq same
    subst second
    rfl
  | some value =>
    symm
    apply anchor_unique second value
    · exact same.mem_iff.mp (anchor_member first value selected)
    · intro member present
      exact anchor_le_member first value member selected (same.mem_iff.mpr present)

theorem separate_components_distinct (first second : List Nat) (a b : Nat)
    (apart : ∀ value ∈ first, value ∉ second)
    (one : anchor first = some a) (two : anchor second = some b) : a ≠ b := by
  intro same
  exact apart a (anchor_member first a one) (same ▸ anchor_member second b two)

theorem retained_anchor_stable (old added : List Nat) (value : Nat)
    (selected : anchor old = some value)
    (later : ∀ member ∈ added, value ≤ member) :
    anchor (old ++ added) = some value := by
  apply anchor_unique
  · exact List.mem_append_left _ (anchor_member old value selected)
  · intro member present
    rcases List.mem_append.mp present with previous | fresh
    · exact anchor_le_member old value member selected previous
    · exact later member fresh

theorem merged_anchor (left right : List Nat) (a b : Nat)
    (one : anchor left = some a) (two : anchor right = some b) :
    anchor (left ++ right) = some (min a b) := by
  apply anchor_unique
  · by_cases order : a ≤ b
    · rw [Nat.min_eq_left order]
      exact List.mem_append_left _ (anchor_member left a one)
    · rw [Nat.min_eq_right (by omega)]
      exact List.mem_append_right _ (anchor_member right b two)
  · intro member present
    rcases List.mem_append.mp present with oldLeft | oldRight
    · exact Nat.le_trans (Nat.min_le_left _ _)
        (anchor_le_member left a member one oldLeft)
    · exact Nat.le_trans (Nat.min_le_right _ _)
        (anchor_le_member right b member two oldRight)

theorem split_retaining_anchor (whole part : List Nat) (value : Nat)
    (selected : anchor whole = some value) (subset : ∀ row ∈ part, row ∈ whole)
    (retained : value ∈ part) : anchor part = some value := by
  exact anchor_unique part value retained (fun row present =>
    anchor_le_member whole value row selected (subset row present))

inductive Key where
  | identifier (value : Nat)
  | component (value : Nat)
  | name (value : Nat)
  deriving DecidableEq, BEq, Repr

def key (identifier component : Option Nat) (name : Nat) : Key :=
  match identifier, component with
  | some value, _ => .identifier value
  | none, some value => .component value
  | none, none => .name name

def aliases (identifier component : Option Nat) (name : Nat) : List Key :=
  (identifier.toList.map Key.identifier) ++ (component.toList.map Key.component) ++
    if identifier.isNone && component.isNone then [.name name] else []

theorem namesakes_separate (a b name : Nat) (different : a ≠ b) :
    key none (some a) name ≠ key none (some b) name := by
  simpa [key] using different

theorem component_not_external (a b : Nat) :
    key none (some a) b ≠ key (some a) none b := by simp [key]

theorem component_alias_retained_on_enrichment (identifier component name : Nat) :
    Key.component component ∈ aliases (some identifier) (some component) name := by
  simp [aliases]

theorem anonymous_component_not_name_claim (component name : Nat) :
    Key.name name ∉ aliases none (some component) name := by simp [aliases]

def componentAliases (rows : List Nat) : List Key := rows.map Key.component

theorem former_anchor_remains_claimable (former current : List Nat) (value : Nat)
    (selected : anchor former = some value)
    (retained : ∀ row ∈ former, row ∈ current) :
    Key.component value ∈ componentAliases current := by
  simp only [componentAliases, List.mem_map]
  exact ⟨value, retained value (anchor_member former value selected), rfl⟩

theorem merged_aliases_preserve_both_histories (left right : List Nat)
    (a b : Nat) (one : anchor left = some a) (two : anchor right = some b) :
    Key.component a ∈ componentAliases (left ++ right) ∧
      Key.component b ∈ componentAliases (left ++ right) := by
  exact ⟨former_anchor_remains_claimable left _ a one
      (fun _ member => List.mem_append_left _ member),
    former_anchor_remains_claimable right _ b two
      (fun _ member => List.mem_append_right _ member)⟩

theorem component_alias_exact (rows : List Nat) (value : Nat) :
    Key.component value ∈ componentAliases rows ↔ value ∈ rows := by
  simp [componentAliases]

structure Row where
  occurrence : Nat
  owner : Key
  datum : Nat
  deriving DecidableEq, Repr

def history (owner : Key) (rows : List Row) : List Row :=
  rows.filter (fun row => decide (row.owner = owner))

theorem history_exact (owner : Key) (rows : List Row) (row : Row) :
    row ∈ history owner rows ↔ row ∈ rows ∧ row.owner = owner := by simp [history]

theorem selected_once (first second : Key) (rows : List Row) (row : Row)
    (one : row ∈ history first rows) (two : row ∈ history second rows) :
    first = second := by
  have a := (history_exact first rows row).mp one
  have b := (history_exact second rows row).mp two
  exact a.2.symm.trans b.2

theorem no_namesake_leak (a b name : Nat) (rows : List Row) (row : Row)
    (apart : a ≠ b) (one : row ∈ history (key none (some a) name) rows) :
    row ∉ history (key none (some b) name) rows := by
  intro two
  exact namesakes_separate a b name apart (selected_once _ _ rows row one two)

theorem history_order_preserved (owner : Key) (rows : List Row) :
    (history owner rows).Sublist rows := List.filter_sublist

/-- Reserved prefix tokens stand for name:, component:, and id: respectively. -/
inductive StorageKey where
  | identifier (value : List Nat)
  | component (value : List Nat)
  | name (value : List Nat)
  deriving DecidableEq, Repr

def encode : StorageKey → List Nat
  | .name value => 0 :: value
  | .component value => 1 :: value
  | .identifier [] => []
  | .identifier (head :: rest) =>
    if head ≤ 2 then 2 :: head :: rest else head :: rest

def decode : List Nat → StorageKey
  | 0 :: rest => .name rest
  | 1 :: rest => .component rest
  | 2 :: rest => .identifier rest
  | other => .identifier other

theorem decode_encode (value : StorageKey) : decode (encode value) = value := by
  cases value with
  | name text => rfl
  | component text => rfl
  | identifier text =>
    cases text with
    | nil => rfl
    | cons head rest =>
      by_cases reserved : head ≤ 2
      · simp [encode, reserved, decode]
      · cases head with
        | zero => omega
        | succ head =>
          cases head with
          | zero => omega
          | succ head =>
            cases head with
            | zero => omega
            | succ head => simp [encode, reserved, decode]

theorem storage_encoding_injective (first second : StorageKey)
    (same : encode first = encode second) : first = second := by
  have decoded := congrArg decode same
  simpa only [decode_encode] using decoded

theorem storage_component_external_disjoint (component identifier : List Nat) :
    encode (.component component) ≠ encode (.identifier identifier) := by
  intro same
  have impossible := storage_encoding_injective _ _ same
  cases impossible

theorem storage_name_external_disjoint (name identifier : List Nat) :
    encode (.name name) ≠ encode (.identifier identifier) := by
  intro same
  have impossible := storage_encoding_injective _ _ same
  cases impossible

end PeriScribe.ComponentIdentity
