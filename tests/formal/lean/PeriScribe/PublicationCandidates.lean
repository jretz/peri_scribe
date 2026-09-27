import PeriScribe.Grouping

namespace PeriScribe.PublicationCandidates

/-- A minimum over a nonempty component has no sentinel collision with real clocks. -/
def minimum : List Nat → Option Nat
  | [] => none
  | first :: rest => some (min first ((minimum rest).getD first))

theorem minimum_is_below_members (values : List Nat) (value result : Nat)
    (present : value ∈ values) (selected : minimum values = some result) :
    result ≤ value := by
  induction values generalizing result with
  | nil => simp at present
  | cons first rest induction =>
    simp only [minimum, Option.some.injEq] at selected
    rcases List.mem_cons.mp present with same | later
    · subst value
      omega
    · cases tail : minimum rest with
      | none =>
        have nonempty : minimum rest ≠ none := by
          cases rest with
          | nil => simp at later
          | cons => simp [minimum]
        exact False.elim (nonempty tail)
      | some old =>
        have bounded := induction old later tail
        simp [tail] at selected
        omega

theorem minimum_is_existing_evidence (values : List Nat) (result : Nat)
    (selected : minimum values = some result) : result ∈ values := by
  induction values generalizing result with
  | nil => simp [minimum] at selected
  | cons first rest induction =>
    cases tail : minimum rest with
    | none =>
      have same : result = first := by simpa [minimum, tail] using selected.symm
      simp [same]
    | some old =>
      have present := induction old tail
      simp only [minimum, tail, Option.getD_some, Option.some.injEq] at selected
      by_cases earlier : first ≤ old
      · simp [Nat.min_eq_left earlier] at selected
        simp [← selected]
      · simp [Nat.min_eq_right (by omega : old ≤ first)] at selected
        simp [← selected, present]

def captured (nodes : List Nat) (component times : Nat → Nat) (node : Nat) : Nat :=
  (minimum ((nodes.filter (fun other => component other == component node)).map times))
    |>.getD 0

theorem connected_aliases_have_same_capture (nodes : List Nat)
    (component times : Nat → Nat) (first second : Nat)
    (same : component first = component second) :
    captured nodes component times first = captured nodes component times second := by
  simp only [captured, same]

theorem constant_component_minimum (nodes : List Nat) (value : Nat)
    (nonempty : nodes ≠ []) : minimum (nodes.map (fun _ => value)) = some value := by
  induction nodes with
  | nil => contradiction
  | cons first rest induction =>
    cases rest with
    | nil => simp [minimum]
    | cons next tail =>
      change some (min value
        ((minimum ((next :: tail).map (fun _ => value))).getD value)) = some value
      rw [induction (by simp)]
      simp

theorem capture_propagation_is_idempotent (nodes : List Nat)
    (component times : Nat → Nat)
    (node : Nat) (present : node ∈ nodes) :
    captured nodes component (captured nodes component times) node =
      captured nodes component times node := by
  have contained :
      node ∈ nodes.filter (fun other => component other == component node) :=
    List.mem_filter.mpr ⟨present, by simp⟩
  have nonempty :
      nodes.filter (fun other => component other == component node) ≠ [] := by
    intro empty
    simp [empty] at contained
  have uniform :
      (nodes.filter (fun other => component other == component node)).map
        (captured nodes component times) =
      (nodes.filter (fun other => component other == component node)).map
        (fun _ => captured nodes component times node) := by
    apply List.map_congr_left
    intro other member
    exact connected_aliases_have_same_capture nodes component times other node
      (by simpa using (List.mem_filter.mp member).2)
  change (minimum ((nodes.filter (fun other => component other == component node)).map
    (captured nodes component times))).getD 0 = captured nodes component times node
  rw [uniform, constant_component_minimum _ _ nonempty]
  rfl

theorem capture_never_moves_forward (nodes : List Nat) (component times : Nat → Nat)
    (node : Nat) (present : node ∈ nodes) :
    captured nodes component times node ≤ times node := by
  have member : times node ∈
      (nodes.filter (fun other => component other == component node)).map times := by
    exact List.mem_map.mpr ⟨node, List.mem_filter.mpr ⟨present, by simp⟩, rfl⟩
  unfold captured
  cases selected : minimum
      ((nodes.filter (fun other => component other == component node)).map times) with
  | none => simp
  | some result => exact minimum_is_below_members _ _ _ member selected

structure Mapping where
  identity : Nat
  identifiers : List Nat
  order : Nat
  capturedAt : Nat
  shape : Nat
  area : Option Nat
  collapsed : Bool := false
  deriving Repr

/-- Mapping vertices connect only through shared identifiers for the same shape. -/
def captureEdges (mappings : List Mapping) : List Grouping.Edge :=
  (List.range mappings.length).flatMap fun first =>
    ((List.range mappings.length).filter fun second =>
      match mappings[first]?, mappings[second]? with
      | some left, some right => left.shape == right.shape &&
          left.identifiers.any right.identifiers.contains
      | _, _ => false).map (first, ·)

def firstCaptures (mappings : List Mapping) : List Nat :=
  let components := Grouping.tableLabels mappings.length (captureEdges mappings)
  let component := fun node => (components[node]?).getD node
  let times := fun node => ((mappings[node]?).map Mapping.capturedAt).getD 0
  (List.range mappings.length).map
    (captured (List.range mappings.length) component times)

theorem capture_edges_reference_existing_mappings (mappings : List Mapping)
    (edge : Grouping.Edge) (present : edge ∈ captureEdges mappings) :
    edge.1 < mappings.length ∧ edge.2 < mappings.length := by
  rcases List.mem_flatMap.mp present with ⟨first, firstInside, edgePresent⟩
  rcases List.mem_map.mp edgePresent with ⟨second, secondInside, same⟩
  cases same
  exact ⟨List.mem_range.mp firstInside,
    List.mem_range.mp (List.mem_filter.mp secondInside).1⟩

theorem first_captures_share_earliest_connected_clock (mappings : List Mapping)
    (first second : Nat) (firstInside : first < mappings.length)
    (secondInside : second < mappings.length)
    (connected : Grouping.Connected (captureEdges mappings) first second) :
    (firstCaptures mappings)[first]? = (firstCaptures mappings)[second]? := by
  have valid := capture_edges_reference_existing_mappings mappings
  have same := Grouping.labels_complete _ connected
  have firstRefines := Grouping.table_union_refines_union mappings.length
    (captureEdges mappings) valid first firstInside
  have secondRefines := Grouping.table_union_refines_union mappings.length
    (captureEdges mappings) valid second secondInside
  simp only [firstCaptures, List.getElem?_map, List.getElem?_range firstInside,
    List.getElem?_range secondInside, Option.map_some]
  congr 1
  apply connected_aliases_have_same_capture
  exact firstRefines.trans (same.trans secondRefines.symm)

/-- Input aliases are validated as a unique published identity relation. -/
def keyFor (identifiers owners : List Nat) : Option Nat :=
  match identifiers, owners with
  | [], _ => none
  | first :: rest, [] => some ((minimum (first :: rest)).getD first)
  | _ :: _, [key] => some key
  | _, _ => none

theorem ambiguity_requires_build (identifiers : List Nat) (first second : Nat)
    (rest : List Nat) : keyFor identifiers (first :: second :: rest) = none := by
  cases identifiers <;> rfl

theorem accepted_key_preserves_known_owner (identifiers owners : List Nat)
    (key previous : Nat) (accepted : keyFor identifiers owners = some key)
    (known : previous ∈ owners) : previous = key := by
  cases identifiers with
  | nil => simp [keyFor] at accepted
  | cons first rest =>
    cases owners with
    | nil => simp at known
    | cons owner others =>
      cases others with
      | nil =>
        have equal : owner = key := by simpa [keyFor] using accepted
        simpa [equal] using known
      | cons => simp [keyFor] at accepted

structure Candidates where
  aliases : List (Nat × Nat)
  mappings : List (Nat × Mapping)
  deriving Repr

def lookup (aliases : List (Nat × Nat)) (identifier : Nat) : Option Nat :=
  (aliases.find? (fun pair => pair.1 == identifier)).map Prod.snd

def replaceCandidate (mappings : List (Nat × Mapping)) (key : Nat) (current : Mapping) :
    List (Nat × Mapping) :=
  match mappings with
  | [] => [(key, current)]
  | (oldKey, previous) :: rest =>
    if oldKey = key then
      (key, if previous.order < current.order then current else previous) :: rest
    else (oldKey, previous) :: replaceCandidate rest key current

def candidate (mappings : List (Nat × Mapping)) (key : Nat) : Option Mapping :=
  (mappings.find? (fun pair => pair.1 == key)).map Prod.snd

def newest (previous : Option Mapping) (current : Mapping) : Mapping :=
  match previous with
  | none => current
  | some old => if old.order < current.order then current else old

theorem newest_is_at_least_current (previous : Option Mapping) (current : Mapping) :
    current.order ≤ (newest previous current).order := by
  cases previous with
  | none => exact Nat.le_refl _
  | some old =>
    by_cases newer : old.order < current.order
    · simp [newest, newer]
    · simp [newest, newer]
      omega

theorem candidate_replacement_selects_latest (mappings : List (Nat × Mapping))
    (key : Nat) (current : Mapping) :
    candidate (replaceCandidate mappings key current) key =
      some (newest (candidate mappings key) current) := by
  induction mappings with
  | nil => simp [candidate, replaceCandidate, newest]
  | cons first rest induction =>
    rcases first with ⟨oldKey, previous⟩
    by_cases same : oldKey = key
    · subst oldKey
      simp [candidate, replaceCandidate, newest]
    · simpa [candidate, replaceCandidate, same] using induction

theorem candidate_replacement_never_selects_an_older_mapping
    (mappings : List (Nat × Mapping)) (key : Nat) (current result : Mapping)
    (selected : candidate (replaceCandidate mappings key current) key = some result) :
    current.order ≤ result.order := by
  rw [candidate_replacement_selects_latest] at selected
  cases Option.some.inj selected
  exact newest_is_at_least_current _ _

def addCandidate (state : Candidates) (current : Mapping) : Option Candidates :=
  if current.collapsed then some state else
  let owners := (current.identifiers.filterMap (lookup state.aliases)).eraseDups
  (keyFor current.identifiers owners).map fun key =>
    ⟨current.identifiers.map (·, key) ++
      state.aliases.filter (fun pair => !current.identifiers.contains pair.1),
      replaceCandidate state.mappings key current⟩

def candidateFold (state : Option Candidates) : List Mapping → Option Candidates
  | [] => state
  | current :: rest => candidateFold (state.bind (addCandidate · current)) rest

theorem collapsed_mapping_cannot_change_candidates (state : Candidates)
    (current : Mapping) (collapsed : current.collapsed = true) :
    addCandidate state current = some state := by simp [addCandidate, collapsed]

theorem uncertain_candidates_cannot_become_a_skip (mappings : List Mapping) :
    candidateFold none mappings = none := by
  induction mappings with
  | nil => rfl
  | cons first rest induction => simpa [candidateFold] using induction

/-- An observation's order is the lexicographic mapping order, abstracted as a rank. -/
structure Comparison where
  current : Mapping
  baseline : Option Mapping
  deriving Repr

def change (comparison : Comparison) : Option (Option Int) :=
  match comparison.baseline with
  | some previous =>
    if comparison.current.order < previous.order then none else
    match comparison.current.area, previous.area with
    | some current, some baseline => some (some ((current : Int) - baseline))
    | _, _ => some none
  | none => some (comparison.current.area.map Int.ofNat)

theorem older_mapping_is_ineligible (current previous : Mapping)
    (older : current.order < previous.order) :
    change ⟨current, some previous⟩ = none := by
  simp [change, older]

structure Signal where
  amount : Int := 0
  identity : Option Nat := none
  deriving Repr

def stronger (previous : Signal) (current : Int) (identity : Nat) : Signal :=
  if previous.amount.natAbs < current.natAbs then ⟨current, some identity⟩ else previous

def largest (changes : List (Int × Nat)) (previous : Signal := {}) : Signal :=
  changes.foldl (fun result value => stronger result value.1 value.2) previous

theorem stronger_dominates_both (previous : Signal) (current : Int) (identity : Nat) :
    previous.amount.natAbs ≤ (stronger previous current identity).amount.natAbs ∧
      current.natAbs ≤ (stronger previous current identity).amount.natAbs := by
  unfold stronger
  split <;> simp_all <;> omega

theorem largest_preserves_prior_magnitude (changes : List (Int × Nat))
    (previous : Signal) :
    previous.amount.natAbs ≤ (largest changes previous).amount.natAbs := by
  induction changes generalizing previous with
  | nil => exact Nat.le_refl _
  | cons first rest induction =>
    exact Nat.le_trans (stronger_dominates_both previous first.1 first.2).1
      (induction (stronger previous first.1 first.2))

theorem largest_dominates_every_change (changes : List (Int × Nat))
    (previous : Signal) (value : Int × Nat) (present : value ∈ changes) :
    value.1.natAbs ≤ (largest changes previous).amount.natAbs := by
  induction changes generalizing previous with
  | nil => simp at present
  | cons first rest induction =>
    rcases List.mem_cons.mp present with same | later
    · subst value
      exact Nat.le_trans (stronger_dominates_both previous first.1 first.2).2
        (largest_preserves_prior_magnitude rest (stronger previous first.1 first.2))
    · exact induction _ later

theorem largest_has_an_actual_measurement_witness (changes : List (Int × Nat))
    (previous : Signal) : largest changes previous = previous ∨
      ∃ value ∈ changes, largest changes previous = ⟨value.1, some value.2⟩ := by
  induction changes generalizing previous with
  | nil => exact Or.inl rfl
  | cons first rest induction =>
    change largest rest (stronger previous first.1 first.2) = previous ∨ _
    rcases induction (stronger previous first.1 first.2) with unchanged | changed
    · by_cases larger : previous.amount.natAbs < first.1.natAbs
      · exact Or.inr ⟨first, by simp,
          by simpa [largest, stronger, larger] using unchanged⟩
      · exact Or.inl (by simpa [stronger, larger] using unchanged)
    · rcases changed with ⟨value, present, selected⟩
      exact Or.inr ⟨value, by simp [present], selected⟩

/-- Unknown comparisons force publication independently of earlier known changes. -/
def comparisons (values : List Comparison) (previous : Signal := {}) : Option Signal :=
  match values with
  | [] => some previous
  | current :: rest =>
    match change current with
    | none => comparisons rest previous
    | some none => none
    | some (some amount) =>
      comparisons rest (stronger previous amount current.current.identity)

/-- Eligibility and uncertainty are resolved before the maximum is specified. -/
def eligibleChanges : List Comparison → Option (List (Int × Nat))
  | [] => some []
  | current :: rest =>
    match change current with
    | none => eligibleChanges rest
    | some none => none
    | some (some amount) =>
      (eligibleChanges rest).map ((amount, current.current.identity) :: ·)

theorem comparison_fold_selects_largest_eligible_change (values : List Comparison)
    (previous : Signal) : comparisons values previous =
      (eligibleChanges values).map (largest · previous) := by
  induction values generalizing previous with
  | nil => rfl
  | cons current rest induction =>
    cases selected : change current with
    | none => simpa [comparisons, eligibleChanges, selected] using induction previous
    | some result =>
      cases result with
      | none => simp [comparisons, eligibleChanges, selected]
      | some amount =>
        simp only [comparisons, eligibleChanges, selected, induction]
        cases eligibleChanges rest <;> rfl

theorem comparison_fold_dominates_every_eligible_change (values : List Comparison)
    (known : List (Int × Nat)) (previous result : Signal)
    (eligible : eligibleChanges values = some known)
    (selected : comparisons values previous = some result)
    (value : Int × Nat) (present : value ∈ known) :
    value.1.natAbs ≤ result.amount.natAbs := by
  rw [comparison_fold_selects_largest_eligible_change, eligible] at selected
  cases Option.some.inj selected
  exact largest_dominates_every_change known previous value present

theorem unknown_area_requires_build (current : Comparison) (rest : List Comparison)
    (previous : Signal) (unknown : change current = some none) :
    comparisons (current :: rest) previous = none := by
  simp [comparisons, unknown]

def reaches (signal : Signal) (threshold : Nat) : Bool :=
  decide (0 < signal.amount.natAbs ∧ threshold ≤ signal.amount.natAbs)

theorem threshold_includes_equal_shrinkage (value : Int) (threshold : Nat) :
    reaches ⟨value, none⟩ threshold = reaches ⟨-value, none⟩ threshold := by
  simp [reaches]

/-- Displayed history rows must identify exactly one raw source measurement. -/
structure RawSource where
  file : Nat
  object : Nat
  mapping : Mapping
  deriving Repr

def matchingSources (rows : List RawSource) (file object : Nat) : List RawSource :=
  rows.filter (fun row => row.file == file && row.object == object)

def rawSource (rows : List RawSource) (file object : Nat) : Option Mapping :=
  match matchingSources rows file object with
  | [row] => some row.mapping
  | _ => none

def publishedBaseline (rows : List RawSource) (file object : Nat) (included : Bool) :
    Option (Option Mapping) :=
  (rawSource rows file object).map
    (fun mapping => if included then some mapping else none)

theorem published_source_has_unique_raw_witness (rows : List RawSource)
    (file object : Nat) (mapping : Mapping)
    (selected : rawSource rows file object = some mapping) :
    ∃ row ∈ rows, row.file = file ∧ row.object = object ∧ row.mapping = mapping ∧
      ∀ other ∈ matchingSources rows file object, other = row := by
  unfold rawSource at selected
  cases matching : matchingSources rows file object with
  | nil => simp [matching] at selected
  | cons row rest =>
    cases rest with
    | cons => simp [matching] at selected
    | nil =>
      have same : row.mapping = mapping := by simpa [matching] using selected
      have present : row ∈ matchingSources rows file object := by simp [matching]
      have valid := List.mem_filter.mp present
      simp only [Bool.and_eq_true, beq_iff_eq] at valid
      exact ⟨row, valid.1, valid.2.1, valid.2.2, same,
        by intro other member; simpa [matching] using member⟩

theorem duplicate_raw_sources_cannot_supply_a_baseline (rows : List RawSource)
    (file object : Nat) (first second : RawSource) (rest : List RawSource)
    (duplicate : matchingSources rows file object = first :: second :: rest) :
    rawSource rows file object = none := by simp [rawSource, duplicate]

theorem excluded_fire_has_no_displayed_area_baseline (rows : List RawSource)
    (file object : Nat) (mapping : Mapping)
    (identified : rawSource rows file object = some mapping) :
    publishedBaseline rows file object false = some none := by
  simp [publishedBaseline, identified]

end PeriScribe.PublicationCandidates
