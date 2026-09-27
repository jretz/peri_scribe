import PeriScribe.IdentityTransfer

namespace PeriScribe.IdentityRecomputation

open IdentityTransfer

def won (histories : List Nat) (winner : Nat → Option Nat) (fire : Nat) : List Nat :=
  histories.filter (fun history => winner history == some fire)

def allocate (histories : List Nat) (winner : Nat → Option Nat)
    (preferred : Nat → Option Nat) (fresh : Nat → Nat) (fire : Nat) : Nat :=
  (chooseWriter (won histories winner fire) (preferred fire)).getD (fresh fire)

theorem selected_writer_has_winner_or_fresh_witness (histories : List Nat)
    (winner : Nat → Option Nat) (preferred : Nat → Option Nat) (fresh : Nat → Nat)
    (fire : Nat) :
    (allocate histories winner preferred fresh fire ∈ histories ∧
      winner (allocate histories winner preferred fresh fire) = some fire) ∨
    allocate histories winner preferred fresh fire = fresh fire := by
  cases chosen : chooseWriter (won histories winner fire) (preferred fire) with
  | none => simp [allocate, chosen]
  | some writer =>
    have member := writer_always_belongs_to_won_histories _ _ _ chosen
    have exact := List.mem_filter.mp member
    exact Or.inl (by simpa [allocate, chosen] using exact)

theorem allocation_derives_unique_writers (histories : List Nat)
    (winner : Nat → Option Nat) (preferred : Nat → Option Nat) (fresh : Nat → Nat)
    (freshUnused : ∀ fire, fresh fire ∉ histories)
    (freshDistinct : ∀ first second, fresh first = fresh second → first = second)
    (first second : Nat)
    (same : allocate histories winner preferred fresh first =
      allocate histories winner preferred fresh second) : first = second := by
  rcases selected_writer_has_winner_or_fresh_witness histories winner preferred fresh
    first with claimedFirst | freshFirst
  · rcases selected_writer_has_winner_or_fresh_witness histories winner preferred fresh
      second with claimedSecond | freshSecond
    · exact Option.some.inj (claimedFirst.2.symm.trans (same ▸ claimedSecond.2))
    · exact False.elim (freshUnused second (same.trans freshSecond ▸ claimedFirst.1))
  · rcases selected_writer_has_winner_or_fresh_witness histories winner preferred fresh
      second with claimedSecond | freshSecond
    · exact False.elim
        (freshUnused first (same.symm.trans freshFirst ▸ claimedSecond.1))
    · exact freshDistinct first second (freshFirst.symm.trans (same.trans freshSecond))

theorem acknowledged_current_mapping_is_inherited (previous current : List (Nat × Nat))
    (owners : Owners) (writer datum : Nat) (selfOwned : owners writer = some writer)
    (recorded : (writer, datum) ∈ current) :
    datum ∈ inheritedRecords owners (acknowledgedRecords previous current) writer := by
  exact (inherited_records_exactly_owned_union _ _ _ _).mpr
    ⟨writer, (acknowledged_record_membership_exact _ _ _ _).mpr (Or.inr recorded),
      selfOwned⟩

theorem stable_writer_recomputation_has_no_novel_mapping
    (previous current : List (Nat × Nat)) (owners : Owners) (writer : Nat)
    (surveys : List Nat) (selfOwned : owners writer = some writer)
    (acknowledged : ∀ datum ∈ surveys, (writer, datum) ∈ current) :
    novel owners (acknowledgedRecords previous current) writer surveys = false := by
  apply Bool.eq_false_iff.mpr
  intro new
  obtain ⟨datum, member, absent⟩ :=
    (novelty_exactly_new_in_inherited_union _ _ _ _).mp new
  exact absent ⟨writer,
    (acknowledged_record_membership_exact _ _ _ _).mpr
      (Or.inr (acknowledged datum member)), selfOwned⟩

/- The current fires have unique report identities and disjoint alias groups. A route
   list is the union of all durable histories reachable through one such group. The
   feedback executor preserves that group boundary while allowing arbitrary overlap
   between its historical routes and those of every other fire. -/
structure Feedback where
  fires : List Fire
  histories : List Nat
  routes : Nat → List Nat
  preferred : Nat → Option Nat
  previous : Nat → Nat
  fresh : Nat → Nat

def candidates (fires : List Fire) (routes : Nat → List Nat) (history : Nat) :
    List Fire := fires.filter (fun fire => (routes fire.identity).contains history)

def winning (fires : List Fire) (routes : Nat → List Nat) (history : Nat) :
    Option Nat := (latest (candidates fires routes history)).map Fire.identity

def writers (input : Feedback) : Nat → Nat :=
  allocate input.histories (winning input.fires input.routes)
    input.preferred input.fresh

def currentIdentities (input : Feedback) : List Nat := input.fires.map Fire.identity

def writerKeys (input : Feedback) : List Nat :=
  (currentIdentities input).map (writers input)

def expanded (input : Feedback) : List Nat := input.histories ++ writerKeys input

def resolved (input : Feedback) (history : Nat) : Nat :=
  if history ∈ writerKeys input then history
  else match winning input.fires input.routes history with
    | none => input.previous history
    | some fire => writers input fire

def learned (input : Feedback) (fire : Nat) : List Nat :=
  input.routes fire ++ (expanded input).filter (fun history =>
    resolved input history == writers input fire)

def largest (histories : List Nat) : Nat := histories.foldr Nat.max 0

theorem member_bounded_by_largest (histories : List Nat) (history : Nat)
    (present : history ∈ histories) : history ≤ largest histories := by
  induction histories with
  | nil => simp at present
  | cons first rest induction =>
    rcases List.mem_cons.mp present with same | member
    · subst history; exact Nat.le_max_left _ _
    · exact Nat.le_trans (induction member) (Nat.le_max_right _ _)

def freshAbove (histories : List Nat) (fire : Nat) : Nat := largest histories + 1 + fire

theorem fresh_above_is_unused (histories : List Nat) (fire : Nat) :
    freshAbove histories fire ∉ histories := by
  intro member
  have bounded := member_bounded_by_largest histories _ member
  simp only [freshAbove] at bounded
  omega

theorem fresh_above_is_injective (histories : List Nat) (first second : Nat)
    (same : freshAbove histories first = freshAbove histories second) :
    first = second := by
  simp only [freshAbove] at same
  omega

def retry (input : Feedback) : Feedback :=
  { input with
    histories := expanded input
    routes := learned input
    preferred := fun fire => some (writers input fire)
    previous := resolved input
    fresh := freshAbove (expanded input) }

structure Valid (input : Feedback) : Prop where
  routesBounded : ∀ fire ∈ input.fires, ∀ history ∈ input.routes fire.identity,
    history ∈ input.histories
  freshUnused : ∀ fire, input.fresh fire ∉ input.histories
  freshDistinct : ∀ first second,
    input.fresh first = input.fresh second → first = second
  identitiesUnique : ∀ first ∈ input.fires, ∀ second ∈ input.fires,
    first.identity = second.identity → first = second

theorem winning_witness (fires : List Fire) (routes : Nat → List Nat)
    (history identity : Nat) (selected : winning fires routes history = some identity) :
    ∃ fire ∈ fires, fire.identity = identity ∧ history ∈ routes fire.identity ∧
      ∀ other ∈ fires, history ∈ routes other.identity → precedes other fire := by
  unfold winning at selected
  cases found : latest (candidates fires routes history) with
  | none => simp [found] at selected
  | some fire =>
    have member := List.mem_filter.mp (latest_has_input_witness _ _ found)
    refine ⟨fire, member.1, by simpa [found] using selected,
      by simpa using member.2, ?_⟩
    intro other present reached
    exact latest_dominates_every_claimant _ _ _ found
      (List.mem_filter.mpr ⟨present, by simpa using reached⟩)

theorem winning_none (fires : List Fire) (routes : Nat → List Nat)
    (history : Nat) : winning fires routes history = none ↔
      ∀ fire ∈ fires, history ∉ routes fire.identity := by
  simp [winning, latest_missing_iff, candidates, List.filter_eq_nil_iff]

theorem winning_of_maximal (fires : List Fire) (routes : Nat → List Nat)
    (history : Nat) (fire : Fire) (present : fire ∈ fires)
    (reached : history ∈ routes fire.identity)
    (maximal : ∀ other ∈ fires, history ∈ routes other.identity → precedes other fire) :
    winning fires routes history = some fire.identity := by
  cases found : winning fires routes history with
  | none => exact False.elim ((winning_none _ _ _).mp found fire present reached)
  | some identity =>
    obtain ⟨other, member, same, route, greatest⟩ := winning_witness _ _ _ _ found
    have equal := equivalent_priority_has_same_identity other fire
      (maximal other member route) (greatest fire present reached)
    simp [← same, equal]

theorem writers_injective (input : Feedback) (valid : Valid input)
    (first second : Nat) (same : writers input first = writers input second) :
    first = second :=
  allocation_derives_unique_writers _ _ _ _ valid.freshUnused valid.freshDistinct
    first second same

theorem writer_old_claim (input : Feedback) (valid : Valid input) (fire : Nat) :
    winning input.fires input.routes (writers input fire) = some fire ∨
      winning input.fires input.routes (writers input fire) = none := by
  rcases selected_writer_has_winner_or_fresh_witness input.histories
    (winning input.fires input.routes) input.preferred input.fresh fire with won | fresh
  · exact Or.inl won.2
  · right
    apply (winning_none _ _ _).mpr
    intro other member reached
    exact valid.freshUnused fire (fresh ▸ valid.routesBounded other member _ reached)

theorem writer_mem (input : Feedback) (fire : Nat)
    (present : fire ∈ currentIdentities input) : writers input fire ∈ expanded input :=
  List.mem_append.mpr (Or.inr (List.mem_map.mpr ⟨fire, present, rfl⟩))

theorem writer_self_owned (input : Feedback) (fire : Nat)
    (present : fire ∈ currentIdentities input) :
    resolved input (writers input fire) = writers input fire := by
  simp [resolved, writerKeys, List.mem_map.mpr ⟨fire, present, rfl⟩]

theorem old_winner_keeps_resolved_owner (input : Feedback) (valid : Valid input)
    (history fire : Nat)
    (winner : winning input.fires input.routes history = some fire) :
    resolved input history = writers input fire := by
  by_cases self : history ∈ writerKeys input
  · obtain ⟨other, member, same⟩ := List.mem_map.mp self
    have old := writer_old_claim input valid other
    rw [same] at old
    rcases old with old | old
    · have equal : other = fire := Option.some.inj (old.symm.trans winner)
      rw [resolved, ite_eq_left self]
      exact same.symm.trans (congrArg (writers input) equal)
    · simp [winner] at old
  · simp [resolved, self, winner]

theorem learned_membership (input : Feedback) (fire history : Nat) :
    history ∈ learned input fire ↔ history ∈ input.routes fire ∨
      (history ∈ expanded input ∧ resolved input history = writers input fire) := by
  simp [learned]

theorem old_winner_survives_learning (input : Feedback) (valid : Valid input)
    (history identity : Nat)
    (winner : winning input.fires input.routes history = some identity) :
    winning input.fires (learned input) history = some identity := by
  obtain ⟨fire, member, same, route, maximal⟩ := winning_witness _ _ _ _ winner
  rw [← same]
  apply winning_of_maximal _ _ _ fire member
    ((learned_membership _ _ _).mpr (Or.inl route))
  intro other present reached
  rcases (learned_membership _ _ _).mp reached with old | acquired
  · exact maximal other present old
  · have sameWriter := acquired.2.symm.trans
      (old_winner_keeps_resolved_owner input valid history identity winner)
    have identityEqual := writers_injective input valid _ _ sameWriter
    have fireEqual := valid.identitiesUnique other present fire member
      (identityEqual.trans same.symm)
    simpa [fireEqual] using priority_reflexive fire

theorem newly_claimed_history_has_resolved_owner (input : Feedback)
    (valid : Valid input)
    (history identity : Nat)
    (winner : winning input.fires (learned input) history = some identity) :
    resolved input history = writers input identity := by
  cases old : winning input.fires input.routes history with
  | some earlier =>
    have unchanged := old_winner_survives_learning input valid history earlier old
    have same := Option.some.inj (unchanged.symm.trans winner)
    simpa [← same] using old_winner_keeps_resolved_owner input valid history earlier old
  | none =>
    obtain ⟨fire, member, same, route, _⟩ := winning_witness _ _ _ _ winner
    rcases (learned_membership _ _ _).mp route with previous | acquired
    · exact False.elim ((winning_none _ _ _).mp old fire member previous)
    · simpa [same] using acquired.2

theorem writer_wins_after_learning (input : Feedback) (valid : Valid input)
    (fire : Fire) (present : fire ∈ input.fires) :
    winning input.fires (learned input) (writers input fire.identity) =
      some fire.identity := by
  have member : fire.identity ∈ currentIdentities input :=
    List.mem_map.mpr ⟨fire, present, rfl⟩
  have reached := (learned_membership input fire.identity
    (writers input fire.identity)).mpr (Or.inr ⟨writer_mem input _ member,
      writer_self_owned input _ member⟩)
  cases chosen : winning input.fires (learned input) (writers input fire.identity) with
  | none => exact False.elim ((winning_none _ _ _).mp chosen fire present reached)
  | some identity =>
    have owned := newly_claimed_history_has_resolved_owner input valid _ _ chosen
    rw [writer_self_owned input _ member] at owned
    exact congrArg some (writers_injective input valid _ _ owned).symm

theorem recomputed_writer_is_derived_stable (input : Feedback) (valid : Valid input)
    (fire : Nat) (present : fire ∈ currentIdentities input) :
    writers (retry input) fire = writers input fire := by
  obtain ⟨current, member, same⟩ := List.mem_map.mp present
  have winner := writer_wins_after_learning input valid current member
  rw [same] at winner
  have won : writers input fire ∈ won (expanded input)
      (winning input.fires (learned input)) fire := by
    simp [IdentityRecomputation.won, writer_mem input fire present, winner]
  change (chooseWriter (IdentityRecomputation.won (expanded input)
    (winning input.fires (learned input)) fire)
    (some (writers input fire))).getD ((retry input).fresh fire) = writers input fire
  rw [preferred_writer_retained_when_won _ _ won]
  rfl

theorem recomputed_writer_keys (input : Feedback) (valid : Valid input) :
    writerKeys (retry input) = writerKeys input := by
  unfold writerKeys
  apply List.map_congr_left
  intro fire member
  exact recomputed_writer_is_derived_stable input valid fire member

theorem recomputed_owners_are_derived_stable (input : Feedback) (valid : Valid input) :
    resolved (retry input) = resolved input := by
  funext history
  have keys := recomputed_writer_keys input valid
  by_cases self : history ∈ writerKeys input
  · simp [resolved, keys, self]
  · rw [resolved]
    simp only [keys, self, ↓reduceIte]
    change (match winning input.fires (learned input) history with
      | none => resolved input history
      | some fire => writers (retry input) fire) = resolved input history
    cases found : winning input.fires (learned input) history with
    | none => rfl
    | some fire =>
      obtain ⟨current, member, same, _, _⟩ := winning_witness _ _ _ _ found
      change writers (retry input) fire = resolved input history
      rw [recomputed_writer_is_derived_stable input valid fire
        (List.mem_map.mpr ⟨current, member, same⟩)]
      exact
        (newly_claimed_history_has_resolved_owner input valid history fire found).symm

theorem expanded_retry_membership (input : Feedback) (valid : Valid input)
    (history : Nat) : history ∈ expanded (retry input) ↔ history ∈ expanded input := by
  change history ∈ (expanded input ++ writerKeys (retry input)) ↔ _
  rw [recomputed_writer_keys input valid]
  simp [expanded]

theorem learned_routes_are_derived_stable (input : Feedback) (valid : Valid input)
    (fire : Nat) (present : fire ∈ currentIdentities input) (history : Nat) :
    history ∈ learned (retry input) fire ↔ history ∈ learned input fire := by
  rw [learned_membership, expanded_retry_membership input valid,
    recomputed_owners_are_derived_stable input valid,
    recomputed_writer_is_derived_stable input valid fire present]
  change (history ∈ learned input fire ∨
    history ∈ expanded input ∧ resolved input history = writers input fire) ↔ _
  rw [learned_membership]
  simp

theorem retry_preserves_valid_domain (input : Feedback) (valid : Valid input) :
    Valid (retry input) := by
  refine ⟨?_, fresh_above_is_unused _, fresh_above_is_injective _,
    valid.identitiesUnique⟩
  intro fire present history member
  rcases (learned_membership _ _ _).mp member with original | added
  · exact List.mem_append.mpr
      (Or.inl (valid.routesBounded fire present history original))
  · exact added.1

def repetitions (input : Feedback) : Nat → Feedback
  | 0 => input
  | count + 1 => retry (repetitions input count)

theorem repetitions_preserve_fires (input : Feedback) (count : Nat) :
    (repetitions input count).fires = input.fires := by
  induction count with
  | zero => rfl
  | succ count induction => simpa [repetitions, retry] using induction

theorem repetitions_preserve_validity (input : Feedback) (valid : Valid input)
    (count : Nat) : Valid (repetitions input count) := by
  induction count with
  | zero => exact valid
  | succ count induction => exact retry_preserves_valid_domain _ induction

theorem arbitrary_retry_count_preserves_writers (input : Feedback) (valid : Valid input)
    (count fire : Nat) (present : fire ∈ currentIdentities input) :
    writers (repetitions input count) fire = writers input fire := by
  induction count with
  | zero => rfl
  | succ count induction =>
    rw [repetitions, recomputed_writer_is_derived_stable _
      (repetitions_preserve_validity input valid count)]
    · exact induction
    · simpa [currentIdentities, repetitions_preserve_fires] using present

theorem arbitrary_retry_count_preserves_owners (input : Feedback) (valid : Valid input)
    (count : Nat) : resolved (repetitions input count) = resolved input := by
  induction count with
  | zero => rfl
  | succ count induction =>
    rw [repetitions, recomputed_owners_are_derived_stable _
      (repetitions_preserve_validity input valid count), induction]

theorem arbitrary_retry_count_preserves_learned_routes (input : Feedback)
    (valid : Valid input) (count fire history : Nat)
    (present : fire ∈ currentIdentities input) :
    history ∈ learned (repetitions input count) fire ↔
      history ∈ learned input fire := by
  induction count with
  | zero => rfl
  | succ count induction =>
    rw [repetitions, learned_routes_are_derived_stable _
      (repetitions_preserve_validity input valid count)]
    · exact induction
    · simpa [currentIdentities, repetitions_preserve_fires] using present

def mappingRecords (input : Feedback) (surveys : Nat → List Nat) : List (Nat × Nat) :=
  input.fires.flatMap (fun fire => (surveys fire.identity).map
    (fun datum => (writers input fire.identity, datum)))

theorem retry_mapping_records_unchanged (input : Feedback) (valid : Valid input)
    (surveys : Nat → List Nat) (count : Nat) :
    mappingRecords (repetitions input count) surveys =
      mappingRecords input surveys := by
  unfold mappingRecords
  rw [repetitions_preserve_fires]
  simp only [List.flatMap_def]
  apply congrArg List.flatten
  apply List.map_congr_left
  intro fire present
  rw [arbitrary_retry_count_preserves_writers input valid count fire.identity
    (List.mem_map.mpr ⟨fire, present, rfl⟩)]

theorem arbitrary_retry_count_adds_no_evidence (input : Feedback) (valid : Valid input)
    (previous : Evidence) (surveys : Nat → List Nat) (count : Nat) :
    acknowledge (acknowledge previous (mappingRecords input surveys))
      (mappingRecords (repetitions input count) surveys) =
        acknowledge previous (mappingRecords input surveys) := by
  rw [retry_mapping_records_unchanged input valid surveys count,
    acknowledgement_idempotent]

theorem arbitrary_retry_count_reports_no_novel_mapping (input : Feedback)
    (valid : Valid input) (previous : List (Nat × Nat)) (surveys : Nat → List Nat)
    (count fire : Nat) (present : fire ∈ currentIdentities input) :
    novel (fun history => some (resolved (repetitions input count) history))
      (acknowledgedRecords previous (mappingRecords input surveys))
      (writers (repetitions input count) fire) (surveys fire) = false := by
  rw [arbitrary_retry_count_preserves_owners input valid count,
    arbitrary_retry_count_preserves_writers input valid count fire present]
  apply stable_writer_recomputation_has_no_novel_mapping
  · exact congrArg some (writer_self_owned input fire present)
  · intro datum member
    obtain ⟨current, currentIn, same⟩ := List.mem_map.mp present
    exact List.mem_flatMap.mpr ⟨current, currentIn,
      List.mem_map.mpr ⟨datum, same ▸ member, by simp [same]⟩⟩

/- The executable maximum is precisely the IdentityTransfer maximum after replacing
   each disjoint current alias group by its complete reachable history list. -/
def aggregate (routes : Nat → List Nat) (fire : Fire) : Fire :=
  { fire with aliases := [], additional := routes fire.identity }

theorem aggregate_preserves_priority (routes : Nat → List Nat) (first second : Fire) :
    precedes (aggregate routes first) (aggregate routes second) ↔
      precedes first second := by rfl

theorem latest_aggregate (routes : Nat → List Nat) (fires : List Fire) :
    latest (fires.map (aggregate routes)) = (latest fires).map (aggregate routes) := by
  induction fires with
  | nil => rfl
  | cons first rest induction =>
    simp only [List.map_cons, latest, induction]
    cases found : latest rest with
    | none => rfl
    | some previous =>
      simp only [Option.map_some, aggregate_preserves_priority]
      split <;> rfl

theorem winning_executes_identity_transfer (fires : List Fire) (routes : Nat → List Nat)
    (history : Nat) : winning fires routes history =
      claimant (fun _ => []) (fires.map (aggregate routes)) history := by
  have filtered : contenders (fun _ => []) (fires.map (aggregate routes)) history =
      (candidates fires routes history).map (aggregate routes) := by
    simp only [contenders, candidates, List.filter_map, reachable, Function.comp_def,
      aggregate, List.flatMap_nil, List.nil_append]
  rw [claimant, filtered, latest_aggregate]
  simp [winning, Option.map_map, aggregate, Function.comp_def]

/- Alias learning writes each group's complete claims and inherited buckets to every
   one of that group's aliases. Disjoint groups make this equal to the route-level
   feedback executor even when their old durable histories overlap arbitrarily. -/
def learnAliases (input : Feedback) (aliases : Nat → List Nat) (lineage : Lineage) :
    Lineage := fun alias => lineage alias ++ input.fires.flatMap (fun fire =>
      if alias ∈ aliases fire.identity then learned input fire.identity else [])

theorem learned_alias_membership (input : Feedback) (aliases : Nat → List Nat)
    (lineage : Lineage) (alias history : Nat) :
    history ∈ learnAliases input aliases lineage alias ↔ history ∈ lineage alias ∨
      ∃ fire ∈ input.fires, alias ∈ aliases fire.identity ∧
        history ∈ learned input fire.identity := by
  simp only [learnAliases, List.mem_append, List.mem_flatMap]
  apply or_congr Iff.rfl
  apply exists_congr
  intro fire
  by_cases member : alias ∈ aliases fire.identity <;> simp [member]

theorem disjoint_alias_learning_refines_complete_routes (input : Feedback)
    (aliases : Nat → List Nat) (lineage : Lineage) (fire : Fire)
    (present : fire ∈ input.fires) (nonempty : aliases fire.identity ≠ [])
    (disjoint : ∀ other ∈ input.fires, ∀ alias ∈ aliases fire.identity,
      alias ∈ aliases other.identity → fire.identity = other.identity)
    (included : ∀ alias ∈ aliases fire.identity, ∀ history ∈ lineage alias,
      history ∈ input.routes fire.identity) (history : Nat) :
    history ∈ (aliases fire.identity).flatMap (learnAliases input aliases lineage) ↔
      history ∈ learned input fire.identity := by
  constructor
  · intro member
    obtain ⟨alias, ownAlias, known⟩ := List.mem_flatMap.mp member
    rcases (learned_alias_membership _ _ _ _ _).mp known with old | added
    · exact (learned_membership _ _ _).mpr
        (Or.inl (included alias ownAlias history old))
    · obtain ⟨other, otherIn, shared, reached⟩ := added
      simpa [disjoint other otherIn alias ownAlias shared] using reached
  · intro member
    obtain ⟨alias, ownAlias⟩ := List.exists_mem_of_ne_nil _ nonempty
    exact List.mem_flatMap.mpr ⟨alias, ownAlias,
      (learned_alias_membership _ _ _ _ _).mpr
        (Or.inr ⟨fire, present, ownAlias, member⟩)⟩

theorem every_alias_route_stabilizes_after_acknowledgement (input : Feedback)
    (valid : Valid input) (aliases : Nat → List Nat) (lineage : Lineage)
    (count alias history : Nat) :
    history ∈ learnAliases (repetitions input count) aliases
      (learnAliases input aliases lineage) alias ↔
        history ∈ learnAliases input aliases lineage alias := by
  rw [learned_alias_membership, learned_alias_membership]
  simp only [repetitions_preserve_fires]
  have same : (∃ fire ∈ input.fires, alias ∈ aliases fire.identity ∧
      history ∈ learned (repetitions input count) fire.identity) ↔
      ∃ fire ∈ input.fires, alias ∈ aliases fire.identity ∧
        history ∈ learned input fire.identity := by
    apply exists_congr
    intro fire
    by_cases present : fire ∈ input.fires
    · simp only [present, true_and]
      rw [arbitrary_retry_count_preserves_learned_routes input valid count fire.identity
        history (List.mem_map.mpr ⟨fire, present, rfl⟩)]
    · simp [present]
  rw [same]
  simp

/- Finite materialization changes evaluation cost, not the feedback algorithm. It
   prevents oracle evaluation from repeatedly expanding prior functional checkpoints. -/
def memoLookup {Value : Type} (fallback : Nat → Value) :
    List (Nat × Value) → Nat → Value
  | [], key => fallback key
  | (stored, value) :: rest, key =>
    if key = stored then value else memoLookup fallback rest key

structure Memo (Value : Type) where
  entries : List (Nat × Value)
  fallback : Nat → Value

def memo {Value : Type} (keys : List Nat) (values : Nat → Value) : Memo Value :=
  ⟨keys.map (fun key => (key, values key)), values⟩

def Memo.get {Value : Type} (table : Memo Value) : Nat → Value :=
  memoLookup table.fallback table.entries

theorem finite_memo_is_extensionally_equal {Value : Type} (keys : List Nat)
    (values : Nat → Value) : (memo keys values).get = values := by
  funext key
  induction keys with
  | nil => rfl
  | cons first rest induction =>
    by_cases same : key = first
    · simp [memo, Memo.get, memoLookup, same]
    · simpa [memo, Memo.get, memoLookup, same] using induction

def materializedRetry (input : Feedback) : Feedback :=
  let winners := (memo input.histories (winning input.fires input.routes)).get
  let selected := (memo (currentIdentities input)
    (allocate input.histories winners input.preferred input.fresh)).get
  let keys := (currentIdentities input).map selected
  let histories := input.histories ++ keys
  let owners := (memo histories (fun history =>
    if history ∈ keys then history
    else match winners history with
      | none => input.previous history
      | some fire => selected fire)).get
  let routes := (memo (currentIdentities input) (fun fire =>
    input.routes fire ++ histories.filter
      (fun history => owners history == selected fire))).get
  { input with
    histories := histories
    routes := routes
    preferred := fun fire => some (selected fire)
    previous := owners
    fresh := freshAbove histories }

theorem materialized_retry_executes_proved_feedback (input : Feedback) :
    materializedRetry input = retry input := by
  simp only [materializedRetry, finite_memo_is_extensionally_equal]
  rfl

def materializedRepetitions (input : Feedback) : Nat → Feedback
  | 0 => input
  | count + 1 => materializedRetry (materializedRepetitions input count)

theorem materialized_repetitions_execute_proved_feedback (input : Feedback)
    (count : Nat) : materializedRepetitions input count = repetitions input count := by
  induction count with
  | zero => rfl
  | succ count induction =>
    simp only [materializedRepetitions, materialized_retry_executes_proved_feedback,
      induction, repetitions]


def recordsWithWriters (fires : List Fire) (selected : Nat → Nat)
    (surveys : Nat → List Nat) : List (Nat × Nat) :=
  fires.flatMap (fun fire => (surveys fire.identity).map
    (fun datum => (selected fire.identity, datum)))

theorem materialized_records_execute_proved_acknowledgement (input : Feedback)
    (surveys : Nat → List Nat) :
    recordsWithWriters input.fires
      (fun fire => ((materializedRetry input).preferred fire).getD 0) surveys =
        mappingRecords input surveys := by
  rw [materialized_retry_executes_proved_feedback]
  rfl

end PeriScribe.IdentityRecomputation
