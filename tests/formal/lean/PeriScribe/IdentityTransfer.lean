import Std

namespace PeriScribe.IdentityTransfer

/- Durable history keys do not change when a correction changes their current owner.
   Claim ordering, alias resolution, and selection of claimed history keys are inputs.
   An evidence pair names its durable bucket explicitly; ownership never moves it. -/
abbrev Owners := Nat → Option Nat
abbrev Evidence := Nat → Nat → Bool

structure Claim where
  claimant : Nat
  histories : List Nat
  deriving DecidableEq, Repr

structure Publication where
  claims : List Claim
  records : List (Nat × Nat)
  deriving DecidableEq, Repr

structure State where
  owners : Owners
  evidence : Evidence

def assign (owners : Owners) (claim : Claim) : Owners := fun history =>
  if history ∈ claim.histories then some claim.claimant else owners history

def claims (owners : Owners) : List Claim → Owners
  | [] => owners
  | claim :: rest => claims (assign owners claim) rest

def matching (values : List Claim) (history : Nat) : List Claim :=
  values.filter (fun claim => claim.histories.contains history)

def lastClaim (values : List Claim) (history : Nat) : Option Nat :=
  ((matching values history).getLast?).map Claim.claimant

theorem single_claim_changes_only_declared_histories (owners : Owners) (claim : Claim)
    (history : Nat) (unclaimed : history ∉ claim.histories) :
    assign owners claim history = owners history := by simp [assign, unclaimed]

theorem single_claim_has_one_current_owner (owners : Owners) (claim : Claim)
    (history : Nat) (claimed : history ∈ claim.histories) :
    assign owners claim history = some claim.claimant := by simp [assign, claimed]

theorem claim_sequence_append (owners : Owners) (before after : List Claim) :
    claims owners (before ++ after) = claims (claims owners before) after := by
  induction before generalizing owners with
  | nil => rfl
  | cons first rest ih => simpa [claims] using ih (assign owners first)

theorem last_matching_claim_wins (owners : Owners) (values : List Claim)
    (history : Nat) :
    claims owners values history =
      match lastClaim values history with
      | none => owners history
      | some claimant => some claimant := by
  induction values generalizing owners with
  | nil => rfl
  | cons first rest ih =>
    rw [claims, ih]
    by_cases owned : history ∈ first.histories
    · have matched : matching (first :: rest) history =
          first :: matching rest history := by simp [matching, owned]
      simp only [lastClaim, matched, List.getLast?_cons]
      cases (matching rest history).getLast? <;> simp [assign, owned]
    · simp [lastClaim, matching, owned, assign]

theorem no_current_duplicate_owner (owners : Owners) (values : List Claim)
    (history first second : Nat)
    (firstOwns : claims owners values history = some first)
    (secondOwns : claims owners values history = some second) : first = second := by
  exact Option.some.inj (firstOwns.symm.trans secondOwns)

theorem current_owner_has_last_claim_witness (owners : Owners) (values : List Claim)
    (history claimant : Nat) (changed : owners history ≠ some claimant)
    (selected : claims owners values history = some claimant) :
    ∃ claim, (matching values history).getLast? = some claim ∧
      claim ∈ values ∧ history ∈ claim.histories ∧ claim.claimant = claimant := by
  rw [last_matching_claim_wins] at selected
  cases found : (matching values history).getLast? with
  | none => simp [lastClaim, found, changed] at selected
  | some claim =>
    have member := List.mem_filter.mp (List.mem_of_getLast? found)
    refine ⟨claim, rfl, member.1, by simpa using member.2, ?_⟩
    simpa [lastClaim, found] using selected

theorem irrelevant_claims_preserve_owner (owners : Owners) (values : List Claim)
    (history : Nat) (unclaimed : ∀ claim ∈ values, history ∉ claim.histories) :
    claims owners values history = owners history := by
  rw [last_matching_claim_wins]
  have empty : matching values history = [] := by
    simpa [matching, List.filter_eq_nil_iff] using unclaimed
  simp [lastClaim, empty]

theorem last_appended_claim_wins (owners : Owners) (before : List Claim)
    (current : Claim) (history : Nat) (claimed : history ∈ current.histories) :
    claims owners (before ++ [current]) history = some current.claimant := by
  simp [claim_sequence_append, claims, assign, claimed]

theorem reversible_transfer (owners : Owners) (history first second : Nat) :
    claims owners [⟨first, [history]⟩, ⟨second, [history]⟩, ⟨first, [history]⟩]
      history = some first := by
  simp [claims, assign]

theorem repeating_claim_is_idempotent (owners : Owners) (claim : Claim) :
    assign (assign owners claim) claim = assign owners claim := by
  funext history
  by_cases claimed : history ∈ claim.histories <;> simp [assign, claimed]

theorem repeating_claim_sequence_is_idempotent (owners : Owners) (values : List Claim) :
    claims (claims owners values) values = claims owners values := by
  funext history
  rw [last_matching_claim_wins]
  cases found : lastClaim values history with
  | none => rfl
  | some claimant => simp [last_matching_claim_wins, found]

def acknowledge (evidence : Evidence) (records : List (Nat × Nat)) : Evidence :=
  fun history datum => evidence history datum || records.contains (history, datum)

theorem acknowledgement_exact (evidence : Evidence) (records : List (Nat × Nat))
    (history datum : Nat) : acknowledge evidence records history datum = true ↔
      evidence history datum = true ∨ (history, datum) ∈ records := by
  simp [acknowledge]

theorem previous_evidence_preserved (evidence : Evidence) (records : List (Nat × Nat))
    (history datum : Nat) (previous : evidence history datum = true) :
    acknowledge evidence records history datum = true := by
  simp [acknowledge, previous]

theorem fresh_records_retained (evidence : Evidence) (records : List (Nat × Nat))
    (history datum : Nat) (fresh : (history, datum) ∈ records) :
    acknowledge evidence records history datum = true := by
  simp [acknowledge, fresh]

theorem evidence_never_changes_buckets (evidence : Evidence)
    (records : List (Nat × Nat)) (history datum : Nat)
    (absent : evidence history datum = false)
    (unrecorded : (history, datum) ∉ records) :
    acknowledge evidence records history datum = false := by
  simp [acknowledge, absent, unrecorded]

theorem acknowledgement_idempotent (evidence : Evidence) (records : List (Nat × Nat)) :
    acknowledge (acknowledge evidence records) records =
      acknowledge evidence records := by
  funext history datum
  simp [acknowledge]

theorem acknowledgement_append (evidence : Evidence) (before after : List (Nat × Nat)) :
    acknowledge evidence (before ++ after) = acknowledge (acknowledge evidence before)
      after := by
  funext history datum
  simp [acknowledge, Bool.or_assoc]

def publish (state : State) (publication : Publication) : State :=
  ⟨claims state.owners publication.claims,
    acknowledge state.evidence publication.records⟩

def publications : State → List Publication → State
  | state, [] => state
  | state, first :: rest => publications (publish state first) rest

theorem publication_retry_is_idempotent (state : State) (publication : Publication) :
    publish (publish state publication) publication = publish state publication := by
  simp [publish, repeating_claim_sequence_is_idempotent, acknowledgement_idempotent]

theorem publication_cannot_move_old_evidence (state : State) (publication : Publication)
    (history datum : Nat) (previous : state.evidence history datum = true) :
    (publish state publication).evidence history datum = true :=
  previous_evidence_preserved _ _ _ _ previous

theorem ownership_transfer_does_not_depend_on_evidence (first second : State)
    (publication : Publication) (sameOwners : first.owners = second.owners) :
    (publish first publication).owners = (publish second publication).owners := by
  simp [publish, sameOwners]

theorem evidence_retention_does_not_depend_on_owner (first second : State)
    (publication : Publication) (sameEvidence : first.evidence = second.evidence) :
    (publish first publication).evidence = (publish second publication).evidence := by
  simp [publish, sameEvidence]

theorem publication_sequence_ownership (state : State) (sequence : List Publication) :
    (publications state sequence).owners =
      claims state.owners (sequence.flatMap Publication.claims) := by
  induction sequence generalizing state with
  | nil => rfl
  | cons first rest ih => simp [publications, ih, publish, claim_sequence_append]

theorem publication_sequence_evidence (state : State) (sequence : List Publication) :
    (publications state sequence).evidence =
      acknowledge state.evidence (sequence.flatMap Publication.records) := by
  induction sequence generalizing state with
  | nil => funext history datum; simp [publications, acknowledge]
  | cons first rest ih => simp [publications, ih, publish, acknowledgement_append]

theorem all_publications_preserve_old_records (state : State)
    (sequence : List Publication) (history datum : Nat)
    (previous : state.evidence history datum = true) :
    (publications state sequence).evidence history datum = true := by
  rw [publication_sequence_evidence]
  exact previous_evidence_preserved _ _ _ _ previous

theorem every_publication_record_retained (state : State) (sequence : List Publication)
    (publication : Publication) (history datum : Nat) (present : publication ∈ sequence)
    (recorded : (history, datum) ∈ publication.records) :
    (publications state sequence).evidence history datum = true := by
  rw [publication_sequence_evidence]
  exact fresh_records_retained _ _ _ _
    (List.mem_flatMap.mpr ⟨publication, present, recorded⟩)

/- Current report identities and durable writer keys are separate tokens. Additional
   histories carry direct-key fallback, adoption, or fresh allocation supplied by the
   existing allocator; choosing these histories is not repeated in this policy. -/
abbrev Lineage := Nat → List Nat

structure Fire where
  identity : Nat
  observed : Option Int
  aliases : List Nat
  additional : List Nat
  deriving DecidableEq, Repr

def reachable (lineage : Lineage) (fire : Fire) : List Nat :=
  fire.aliases.flatMap lineage ++ fire.additional

theorem reachable_exact (lineage : Lineage) (fire : Fire) (history : Nat) :
    history ∈ reachable lineage fire ↔
      (∃ alias ∈ fire.aliases, history ∈ lineage alias) ∨
        history ∈ fire.additional := by
  simp [reachable, List.mem_flatMap]

def precedes (first second : Fire) : Prop :=
  match first.observed, second.observed with
  | none, none => first.identity ≤ second.identity
  | none, some _ => True
  | some _, none => False
  | some before, some after =>
    before < after ∨ (before = after ∧ first.identity ≤ second.identity)

instance (first second : Fire) : Decidable (precedes first second) := by
  unfold precedes
  split <;> infer_instance

theorem priority_reflexive (fire : Fire) : precedes fire fire := by
  cases observed : fire.observed <;> simp [precedes, observed]

theorem priority_total (first second : Fire) :
    precedes first second ∨ precedes second first := by
  cases a : first.observed <;> cases b : second.observed <;>
    simp [precedes, a, b] <;> omega

theorem priority_transitive (first second third : Fire)
    (before : precedes first second) (after : precedes second third) :
    precedes first third := by
  cases a : first.observed <;> cases b : second.observed <;>
    cases c : third.observed <;> simp_all [precedes] <;> omega

theorem equivalent_priority_has_same_identity (first second : Fire)
    (forward : precedes first second) (backward : precedes second first) :
    first.identity = second.identity := by
  cases a : first.observed <;> cases b : second.observed <;>
    simp_all [precedes] <;> omega

def latest : List Fire → Option Fire
  | [] => none
  | first :: rest => match latest rest with
    | none => some first
    | some previous => if precedes previous first then some first else some previous

theorem latest_has_input_witness (fires : List Fire) (winner : Fire)
    (selected : latest fires = some winner) : winner ∈ fires := by
  induction fires generalizing winner with
  | nil => simp [latest] at selected
  | cons first rest ih =>
    cases found : latest rest with
    | none =>
      have same : first = winner := by simpa [latest, found] using selected
      simp [← same]
    | some previous =>
      by_cases newer : precedes previous first
      · have same : first = winner := by simpa [latest, found, newer] using selected
        simp [← same]
      · have same : previous = winner := by simpa [latest, found, newer] using selected
        exact List.mem_cons_of_mem _ (same ▸ ih previous found)

theorem latest_missing_iff (fires : List Fire) : latest fires = none ↔ fires = [] := by
  cases fires with
  | nil => simp [latest]
  | cons first rest =>
    cases found : latest rest <;> simp [latest, found]
    split <;> simp

theorem latest_dominates_every_claimant (fires : List Fire) (winner fire : Fire)
    (selected : latest fires = some winner) (present : fire ∈ fires) :
    precedes fire winner := by
  induction fires generalizing winner with
  | nil => simp at present
  | cons first rest ih =>
    cases found : latest rest with
    | none =>
      have empty := (latest_missing_iff rest).mp found
      have same : first = winner := by simpa [latest, found] using selected
      have current : fire = first := by simpa [empty] using present
      simpa [← same, current] using priority_reflexive first
    | some previous =>
      by_cases newer : precedes previous first
      · have same : first = winner := by simpa [latest, found, newer] using selected
        rw [← same]
        rcases List.mem_cons.mp present with current | earlier
        · simpa [current] using priority_reflexive first
        · exact priority_transitive fire previous first
            (ih previous found earlier) newer
      · have same : previous = winner := by simpa [latest, found, newer] using selected
        rw [← same]
        rcases List.mem_cons.mp present with current | earlier
        · subst fire
          exact (priority_total first previous).resolve_right newer
        · exact ih previous found earlier

def contenders (lineage : Lineage) (fires : List Fire) (history : Nat) : List Fire :=
  fires.filter (fun fire => (reachable lineage fire).contains history)

def claimant (lineage : Lineage) (fires : List Fire) (history : Nat) : Option Nat :=
  (latest (contenders lineage fires history)).map Fire.identity

theorem claimant_has_reachable_maximum_witness (lineage : Lineage) (fires : List Fire)
    (history identity : Nat) (chosen : claimant lineage fires history = some identity) :
    ∃ winner ∈ fires, winner.identity = identity ∧ history ∈ reachable lineage winner ∧
      ∀ other ∈ fires, history ∈ reachable lineage other → precedes other winner := by
  unfold claimant at chosen
  cases found : latest (contenders lineage fires history) with
  | none => simp [found] at chosen
  | some winner =>
    have member := List.mem_filter.mp (latest_has_input_witness _ _ found)
    refine ⟨winner, member.1, by simpa [found] using chosen,
      by simpa using member.2, ?_⟩
    intro other present reached
    exact latest_dominates_every_claimant _ _ _ found
      (List.mem_filter.mpr ⟨present, by simpa using reached⟩)

theorem claimant_missing_iff_unreachable (lineage : Lineage) (fires : List Fire)
    (history : Nat) : claimant lineage fires history = none ↔
      ∀ fire ∈ fires, history ∉ reachable lineage fire := by
  simp [claimant, latest_missing_iff, contenders, List.filter_eq_nil_iff]

theorem claimant_independent_of_input_order (lineage : Lineage)
    (first second : List Fire)
    (same : ∀ fire, fire ∈ first ↔ fire ∈ second) (history : Nat) :
    claimant lineage first history = claimant lineage second history := by
  cases a : claimant lineage first history with
  | none =>
    have missing := (claimant_missing_iff_unreachable lineage first history).mp a
    exact ((claimant_missing_iff_unreachable lineage second history).mpr
      (by intro fire member; exact missing fire ((same fire).mpr member))).symm
  | some firstWinner =>
    obtain ⟨firstFire, firstIn, firstId, firstReach, firstMax⟩ :=
      claimant_has_reachable_maximum_witness lineage first history firstWinner a
    cases b : claimant lineage second history with
    | none =>
      have missing := (claimant_missing_iff_unreachable lineage second history).mp b
      exact False.elim (missing firstFire ((same firstFire).mp firstIn) firstReach)
    | some secondWinner =>
      obtain ⟨secondFire, secondIn, secondId, secondReach, secondMax⟩ :=
        claimant_has_reachable_maximum_witness lineage second history secondWinner b
      have eq := equivalent_priority_has_same_identity firstFire secondFire
        (secondMax firstFire ((same firstFire).mp firstIn) firstReach)
        (firstMax secondFire ((same secondFire).mpr secondIn) secondReach)
      simp [← firstId, ← secondId, eq]

def transfer (previous : Owners) (lineage : Lineage) (fires : List Fire)
    (writers : Nat → Nat) : Owners := fun history =>
  match claimant lineage fires history with
  | none => previous history
  | some identity => some (writers identity)

theorem transfer_uses_winners_writer (previous : Owners) (lineage : Lineage)
    (fires : List Fire) (writers : Nat → Nat) (history identity : Nat)
    (winner : claimant lineage fires history = some identity) :
    transfer previous lineage fires writers history = some (writers identity) := by
  simp [transfer, winner]

theorem injective_writer_assignment_preserves_distinct_groups (writers : Nat → Nat)
    (identities : List Nat)
    (injective : ∀ first ∈ identities, ∀ second ∈ identities,
      writers first = writers second → first = second)
    (first second : Nat) (firstPresent : first ∈ identities)
    (secondPresent : second ∈ identities)
    (different : first ≠ second) : writers first ≠ writers second := by
  exact fun same => different (injective first firstPresent second secondPresent same)

def extendLineage (previous : Lineage) (aliases histories : List Nat) : Lineage :=
  fun alias => if alias ∈ aliases then previous alias ++ histories else previous alias

theorem lineage_membership_exact (previous : Lineage) (aliases histories : List Nat)
    (alias history : Nat) : history ∈ extendLineage previous aliases histories alias ↔
      history ∈ previous alias ∨ (alias ∈ aliases ∧ history ∈ histories) := by
  by_cases member : alias ∈ aliases <;> simp [extendLineage, member]

theorem lineage_never_forgets_history (previous : Lineage)
    (aliases histories : List Nat)
    (alias history : Nat) (known : history ∈ previous alias) :
    history ∈ extendLineage previous aliases histories alias := by
  exact (lineage_membership_exact _ _ _ _ _).mpr (Or.inl known)

theorem lineage_reaffirmation_is_idempotent_in_membership (previous : Lineage)
    (aliases histories : List Nat) (alias history : Nat) :
    history ∈ extendLineage (extendLineage previous aliases histories) aliases histories
      alias ↔ history ∈ extendLineage previous aliases histories alias := by
  simp [lineage_membership_exact]

def inheritedRecords (owners : Owners) (records : List (Nat × Nat)) (writer : Nat) :
    List Nat :=
  ((records.filter (fun record => owners record.1 == some writer)).map
    Prod.snd).eraseDups

theorem inherited_records_exactly_owned_union (owners : Owners)
    (records : List (Nat × Nat)) (writer datum : Nat) :
    datum ∈ inheritedRecords owners records writer ↔
      ∃ history, (history, datum) ∈ records ∧ owners history = some writer := by
  simp [inheritedRecords, List.mem_map, and_assoc]

def project (owners : Owners) (events : List (Nat × Nat)) : List (Nat × Nat) :=
  events.map (fun event => ((owners event.1).getD event.1, event.2))

theorem projection_preserves_record_order_and_payloads (owners : Owners)
    (events : List (Nat × Nat)) : (project owners events).map Prod.snd =
      events.map Prod.snd := by simp [project, List.map_map]

theorem projection_preserves_record_count (owners : Owners)
    (events : List (Nat × Nat)) : (project owners events).length = events.length := by
  simp [project]

theorem projection_follows_current_ownership (owners : Owners)
    (history writer datum : Nat)
    (owned : owners history = some writer) :
    project owners [(history, datum)] = [(writer, datum)] := by simp [project, owned]

theorem projection_performs_one_hop (owners : Owners) (history first second datum : Nat)
    (firstOwner : owners history = some first)
    (nextOwner : owners first = some second) :
    project owners [(history, datum), (first, datum)] =
      [(first, datum), (second, datum)] := by simp [project, firstOwner, nextOwner]

theorem cyclic_owner_swap_preserves_both_records (owners : Owners)
    (first second firstDatum secondDatum : Nat)
    (forward : owners first = some second) (backward : owners second = some first) :
    project owners [(first, firstDatum), (second, secondDatum)] =
      [(second, firstDatum), (first, secondDatum)] := by
  simp [project, forward, backward]

def novel (owners : Owners) (records : List (Nat × Nat)) (writer : Nat)
    (current : List Nat) : Bool :=
  current.any (fun datum => !(inheritedRecords owners records writer).contains datum)

theorem novelty_exactly_new_in_inherited_union (owners : Owners)
    (records : List (Nat × Nat)) (writer : Nat) (current : List Nat) :
    novel owners records writer current = true ↔
      ∃ datum ∈ current, ¬ ∃ history, (history, datum) ∈ records ∧
        owners history = some writer := by
  simp [novel, List.any_eq_true, inherited_records_exactly_owned_union]

def acknowledgedRecords (previous current : List (Nat × Nat)) : List (Nat × Nat) :=
  (previous ++ current).eraseDups

theorem acknowledged_record_membership_exact (previous current : List (Nat × Nat))
    (history datum : Nat) : (history, datum) ∈ acknowledgedRecords previous current ↔
      (history, datum) ∈ previous ∨ (history, datum) ∈ current := by
  simp [acknowledgedRecords]

theorem concrete_records_refine_evidence_acknowledgement
    (previous current : List (Nat × Nat)) (history datum : Nat) :
    (history, datum) ∈ acknowledgedRecords previous current ↔
      acknowledge (fun bucket value => previous.contains (bucket, value)) current
        history datum = true := by
  simp [acknowledged_record_membership_exact, acknowledgement_exact]

def chooseWriter (won : List Nat) (preferred : Option Nat) : Option Nat :=
  match preferred with
  | some key => if key ∈ won then some key else won.min?
  | none => won.min?

theorem preferred_writer_retained_when_won (won : List Nat) (preferred : Nat)
    (winner : preferred ∈ won) :
    chooseWriter won (some preferred) = some preferred := by
  simp [chooseWriter, winner]

theorem writer_always_belongs_to_won_histories (won : List Nat) (preferred : Option Nat)
    (writer : Nat) (selected : chooseWriter won preferred = some writer) :
    writer ∈ won := by
  cases preferred with
  | none => exact List.min?_mem selected
  | some key =>
    by_cases member : key ∈ won
    · have same : key = writer := by simpa [chooseWriter, member] using selected
      simpa [← same] using member
    · exact List.min?_mem (by simpa [chooseWriter, member] using selected)

theorem missing_preference_selects_least_won_key (won : List Nat)
    (preferred : Option Nat) (unavailable : ∀ key, preferred = some key → key ∉ won)
    (writer : Nat) (selected : chooseWriter won preferred = some writer) :
    ∀ key ∈ won, writer ≤ key := by
  have minimal : won.min? = some writer := by
    cases preferred with
    | none => exact selected
    | some value => simpa [chooseWriter, unavailable value rfl] using selected
  exact (List.min?_eq_some_iff.mp minimal).2

theorem writer_needs_allocation_exactly_when_no_history_won (won : List Nat)
    (preferred : Option Nat) : chooseWriter won preferred = none ↔ won = [] := by
  cases preferred with
  | none => simp [chooseWriter]
  | some key =>
    by_cases member : key ∈ won
    · simp [chooseWriter, member, List.ne_nil_of_mem member]
    · simp [chooseWriter, member]

def learningHistories (original histories : List Nat) (owners : Owners) (writer : Nat) :
    List Nat :=
  original ++ histories.filter (fun history => owners history == some writer) ++
    [writer]

def learn (previous : Lineage) (aliases original histories : List Nat)
    (owners : Owners) (writer : Nat) : Lineage :=
  extendLineage previous aliases (learningHistories original histories owners writer)

theorem learned_alias_has_exact_history_routes (previous : Lineage)
    (aliases original histories : List Nat) (owners : Owners)
    (writer alias history : Nat) : history ∈ learn previous aliases original histories
      owners writer alias ↔ history ∈ previous alias ∨
      (alias ∈ aliases ∧ (history ∈ original ∨
        (history ∈ histories ∧ owners history = some writer) ∨ history = writer)) := by
  simp [learn, lineage_membership_exact, learningHistories]

theorem losing_claim_route_remains_reclaimable (previous : Lineage)
    (aliases original histories : List Nat) (owners : Owners)
    (writer alias history : Nat) (current : alias ∈ aliases)
    (claimed : history ∈ original) :
    history ∈ learn previous aliases original histories owners writer alias := by
  exact (learned_alias_has_exact_history_routes _ _ _ _ _ _ _ _).mpr
    (Or.inr ⟨current, Or.inl claimed⟩)

end PeriScribe.IdentityTransfer
