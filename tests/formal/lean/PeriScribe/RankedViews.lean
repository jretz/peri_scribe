import Std

namespace PeriScribe.RankedViews

structure Fire where
  owner : Nat
  name : Nat
  identifiers : List Nat
  deriving Repr, DecidableEq

structure Score where
  identifier : Option Nat
  name : Nat
  value : Int
  serial : Nat := 0
  deriving Repr, DecidableEq

/-- Input maps retain their final value; ambiguous names have an explicit last owner. -/
def identifierMatch (fires : List Fire) (score : Score) : Option Fire :=
  score.identifier.bind fun identifier =>
    fires.reverse.find? (fun fire => fire.identifiers.contains identifier)

def resolve (fires : List Fire) (score : Score) : Option Fire :=
  (identifierMatch fires score).or
    (fires.reverse.find? (fun fire => fire.name == score.name))

theorem identifier_match_has_priority (fires : List Fire) (score : Score)
    (fire : Fire) (matched : identifierMatch fires score = some fire) :
    resolve fires score = some fire := by simp [resolve, matched]

theorem resolution_is_showable (fires : List Fire) (score : Score) (fire : Fire)
    (matched : resolve fires score = some fire) : fire ∈ fires := by
  unfold resolve identifierMatch at matched
  cases identifier : score.identifier with
  | none =>
    simp only [identifier, Option.bind_none, Option.or] at matched
    simpa using List.mem_of_find?_eq_some matched
  | some value =>
    simp only [identifier, Option.bind_some] at matched
    cases found : fires.reverse.find? (fun fire => fire.identifiers.contains value) with
    | none =>
      simp only [found, Option.or] at matched
      simpa using List.mem_of_find?_eq_some matched
    | some selected =>
      simp only [found, Option.or, Option.some.injEq] at matched
      subst fire
      simpa using List.mem_of_find?_eq_some found

/-- Retain the first, highest-ranked occurrence of each resolved identity. -/
def retain (key : α → Nat) (seen : List Nat) : List α → List α
  | [] => []
  | first :: rest =>
    if key first ∈ seen then retain key seen rest
    else first :: retain key (key first :: seen) rest

theorem retain_members (key : α → Nat) (seen : List Nat) (rows : List α)
    (row : α) (member : row ∈ retain key seen rows) :
    row ∈ rows ∧ key row ∉ seen := by
  induction rows generalizing seen with
  | nil => simp [retain] at member
  | cons first rest induction =>
    simp only [retain] at member
    split at member
    · obtain ⟨belongs, fresh⟩ := induction seen member
      exact ⟨List.mem_cons_of_mem _ belongs, fresh⟩
    · rcases List.mem_cons.mp member with same | later
      · subst row; simp_all
      · obtain ⟨belongs, fresh⟩ := induction (key first :: seen) later
        exact ⟨List.mem_cons_of_mem _ belongs, fun h => fresh (by simp [h])⟩

theorem retain_is_sublist (key : α → Nat) (seen : List Nat) (rows : List α) :
    (retain key seen rows).Sublist rows := by
  induction rows generalizing seen with
  | nil => simp [retain]
  | cons first rest induction =>
    simp only [retain]
    split
    · exact (induction seen).cons _
    · exact (induction (key first :: seen)).cons_cons _

theorem retain_unique (key : α → Nat) (seen : List Nat) (rows : List α) :
    ((retain key seen rows).map key).Nodup := by
  induction rows generalizing seen with
  | nil => simp [retain]
  | cons first rest induction =>
    simp only [retain]
    split
    · exact induction seen
    · simp only [List.map_cons, List.nodup_cons]
      constructor
      · intro duplicate
        obtain ⟨row, member, same⟩ := List.mem_map.mp duplicate
        have fresh := (retain_members key (key first :: seen) rest row member).2
        exact fresh (by simp [same])
      · exact induction _

theorem retain_map_key (key : α → Nat) (seen : List Nat) (rows : List α) :
    (retain key seen rows).map key = retain id seen (rows.map key) := by
  induction rows generalizing seen with
  | nil => rfl
  | cons first rest induction =>
    simp only [retain, List.map_cons, id_eq]
    split <;> simp_all

theorem retain_keeps_owner_maximum (key : α → Nat) (value : α → Int)
    (seen : List Nat) (rows : List α)
    (ordered : rows.Pairwise (fun a b => value b ≤ value a))
    (row candidate : α) (selected : row ∈ retain key seen rows)
    (belongs : candidate ∈ rows) (same : key candidate = key row) :
    value candidate ≤ value row := by
  induction rows generalizing seen with
  | nil => simp [retain] at selected
  | cons first rest induction =>
    obtain ⟨before, remaining⟩ := List.pairwise_cons.mp ordered
    have fresh := (retain_members key seen _ row selected).2
    simp only [retain] at selected
    split at selected
    · rename_i taken
      rcases List.mem_cons.mp belongs with head | tail
      · subst candidate; exact False.elim (fresh (same ▸ taken))
      · exact induction seen remaining selected tail
    · rcases List.mem_cons.mp selected with head | tail
      · subst row
        rcases List.mem_cons.mp belongs with head | tail
        · subst candidate; omega
        · exact before candidate tail
      · rcases List.mem_cons.mp belongs with head | belongs
        · subst candidate
          have absent := (retain_members key (key first :: seen) rest row tail).2
          exact False.elim (absent (by simp [← same]))
        · exact induction (key first :: seen) remaining tail belongs

def precedes (first second : Score) : Bool :=
  decide (second.value < first.value ∨
    (first.value = second.value ∧ first.name ≤ second.name))

def sorted (scores : List Score) : List Score := scores.mergeSort precedes

theorem scores_are_ordered (scores : List Score) :
    (sorted scores).Pairwise (fun a b => precedes a b = true) := by
  apply List.pairwise_mergeSort
  · intro first middle last one two
    simp only [precedes, decide_eq_true_eq] at *
    omega
  · intro first second
    simp only [precedes, Bool.or_eq_true, decide_eq_true_eq]
    omega

def candidates (fires : List Fire) (scores : List Score) : List Nat :=
  (sorted scores).filterMap fun score => (resolve fires score).map Fire.owner

def top (limit : Nat) (fires : List Fire) (scores : List Score) : List Nat :=
  (retain id [] (candidates fires scores)).take limit

def associations (fires : List Fire) (scores : List Score) : List (Nat × Score) :=
  retain Prod.fst [] ((sorted scores).filterMap fun score =>
    (resolve fires score).map fun fire => (fire.owner, score))

theorem top_and_display_share_owners (limit : Nat) (fires : List Fire)
    (scores : List Score) :
    top limit fires scores = ((associations fires scores).map Prod.fst).take limit := by
  simp only [associations, retain_map_key, List.map_filterMap, top, candidates]
  congr 2
  congr 1
  funext score
  cases resolve fires score <;> rfl

theorem association_owners_are_unique (fires : List Fire) (scores : List Score) :
    ((associations fires scores).map Prod.fst).Nodup := retain_unique _ _ _

theorem associated_score_retains_exact_source (fires : List Fire)
    (scores : List Score) (owner : Nat) (score : Score)
    (selected : (owner, score) ∈ associations fires scores) :
    score ∈ scores ∧ ∃ fire ∈ fires,
      resolve fires score = some fire ∧ fire.owner = owner := by
  have chosen := (retain_members Prod.fst [] _ (owner, score) selected).1
  obtain ⟨source, member, mapped⟩ := List.mem_filterMap.mp chosen
  obtain ⟨fire, found, same⟩ := Option.map_eq_some_iff.mp mapped
  have ownerSame := (Prod.mk.inj same).1
  have scoreSame := (Prod.mk.inj same).2
  subst source
  exact ⟨by simpa [sorted] using member, fire,
    resolution_is_showable fires score fire found, found, ownerSame⟩

theorem associated_score_is_owner_maximum (fires : List Fire) (scores : List Score)
    (owner : Nat) (selected candidate : Score)
    (chosen : (owner, selected) ∈ associations fires scores)
    (source : candidate ∈ scores) (fire : Fire)
    (resolved : resolve fires candidate = some fire) (owned : fire.owner = owner) :
    candidate.value ≤ selected.value := by
  let rows : List (Nat × Score) := (sorted scores).filterMap fun score =>
    (resolve fires score).map fun item => (item.owner, score)
  have ordered : rows.Pairwise (fun a b => b.2.value ≤ a.2.value) := by
    apply List.pairwise_filterMap.mpr
    apply (scores_are_ordered scores).imp
    intro first second ordered a firstMapped b secondMapped
    obtain ⟨firstFire, _, firstSame⟩ := Option.map_eq_some_iff.mp firstMapped
    obtain ⟨secondFire, _, secondSame⟩ := Option.map_eq_some_iff.mp secondMapped
    rw [← firstSame, ← secondSame]
    simp only [precedes, decide_eq_true_eq] at ordered
    change second.value ≤ first.value
    omega
  have member : (owner, candidate) ∈ rows := by
    apply List.mem_filterMap.mpr
    exact ⟨candidate, by simpa [sorted] using source, by simp [resolved, owned]⟩
  exact retain_keeps_owner_maximum Prod.fst (fun item : Nat × Score => item.2.value)
    [] rows ordered (owner, selected) (owner, candidate) chosen member rfl


theorem first_ranked_owner_is_retained (key : α → Nat) (first : α) (rest : List α) :
    retain key [] (first :: rest) = first :: retain key [key first] rest := by
  simp [retain]

theorem top_has_no_duplicates (limit : Nat) (fires : List Fire)
    (scores : List Score) : (top limit fires scores).Nodup := by
  have unique := retain_unique id [] (candidates fires scores)
  simp only [List.map_id] at unique
  exact unique.sublist (List.take_sublist _ _)

theorem top_is_bounded (limit : Nat) (fires : List Fire) (scores : List Score) :
    (top limit fires scores).length ≤ limit := by simp [top]; omega

theorem top_preserves_rank_order (limit : Nat) (fires : List Fire)
    (scores : List Score) :
    (top limit fires scores).Sublist (candidates fires scores) :=
  (List.take_sublist _ _).trans (retain_is_sublist id [] _)

theorem top_has_resolved_evidence (limit : Nat) (fires : List Fire)
    (scores : List Score) (owner : Nat) (member : owner ∈ top limit fires scores) :
    ∃ score ∈ scores, ∃ fire ∈ fires,
      resolve fires score = some fire ∧ fire.owner = owner := by
  have chosen := (retain_members id [] _ owner
    (List.mem_of_mem_take member)).1
  obtain ⟨score, belongs, matched⟩ := List.mem_filterMap.mp chosen
  obtain ⟨fire, found, same⟩ := Option.map_eq_some_iff.mp matched
  exact ⟨score, by simpa [sorted] using belongs, fire,
    resolution_is_showable fires score fire found, found, same⟩

def inWindow (now width observed : Int) : Bool :=
  decide (now - width ≤ observed ∧ observed ≤ now)

theorem window_excludes_future (now width observed : Int)
    (eligible : inWindow now width observed = true) : observed ≤ now := by
  exact (of_decide_eq_true eligible).2

theorem cutoff_is_included (now width : Int) (nonnegative : 0 ≤ width) :
    inWindow now width (now - width) = true := by simp [inWindow]; omega

structure Measurement where
  time : Int
  area : Int
  deriving Repr, DecidableEq

def latest (now : Int) (rows : List Measurement) : Option Measurement :=
  ((rows.filter (fun row => decide (row.time ≤ now))).mergeSort
    (fun a b => decide (a.time ≤ b.time))).getLast?

theorem latest_has_past_evidence (now : Int) (rows : List Measurement)
    (row : Measurement) (chosen : latest now rows = some row) :
    row ∈ rows ∧ row.time ≤ now := by
  have member := List.mem_of_getLast? chosen
  unfold latest at member
  simpa [latest] using member

theorem latest_ignores_future_append (now : Int) (rows : List Measurement)
    (future : Measurement) (later : now < future.time) :
    latest now (rows ++ [future]) = latest now rows := by
  simp [latest, List.filter_append, Int.not_le.mpr later]

theorem latest_is_maximum_past_time (now : Int) (rows : List Measurement)
    (selected candidate : Measurement) (chosen : latest now rows = some selected)
    (member : candidate ∈ rows) (past : candidate.time ≤ now) :
    candidate.time ≤ selected.time := by
  let ordered := (rows.filter (fun row => decide (row.time ≤ now))).mergeSort
    (fun a b => decide (a.time ≤ b.time))
  have ordering : ordered.Pairwise (fun a b => a.time ≤ b.time) := by
    apply List.Pairwise.imp (fun {_ _} relation => of_decide_eq_true relation)
    apply List.pairwise_mergeSort
    · intro a b c one two
      simp only [decide_eq_true_eq] at *
      omega
    · intro a b
      simp only [Bool.or_eq_true, decide_eq_true_eq]
      omega
  have present : candidate ∈ ordered := by simp [ordered, member, past]
  obtain ⟨before, decomposition⟩ := List.getLast?_eq_some_iff.mp chosen
  change ordered = before ++ [selected] at decomposition
  rw [decomposition] at ordering present
  rcases List.mem_append.mp present with earlier | last
  · exact (List.pairwise_append.mp ordering).2.2 candidate earlier selected (by simp)
  · have same : candidate = selected := by simpa using last
    simp [same]

def growth (now width : Int) (rows : List Measurement) : Option (Int × Int) := do
  let current ← latest now rows
  let baseline := (latest (now - width) rows).map Measurement.area |>.getD 0
  return (current.area - baseline, baseline)

def percentEligible (growth baseline minimum : Int) : Bool :=
  decide (0 < baseline ∧ minimum * baseline ≤ growth * 100)

theorem percentage_requires_positive_baseline (growth baseline minimum : Int)
    (eligible : percentEligible growth baseline minimum = true) : 0 < baseline := by
  exact (of_decide_eq_true eligible).1

end PeriScribe.RankedViews
