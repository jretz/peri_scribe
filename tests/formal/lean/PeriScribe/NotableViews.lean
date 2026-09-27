import PeriScribe.RankedViews

namespace PeriScribe.NotableViews

structure Fire where
  identity : RankedViews.Fire
  active : Bool
  discovery : Option Int
  deriving Repr, DecidableEq

structure Score where
  ranked : RankedViews.Score
  area : Option Int
  buildings : Option Int
  evacuation : Bool
  deriving Repr, DecidableEq

structure Row where
  owner : Nat
  name : Nat
  score : Int
  serial : Nat
  active : Bool
  discovery : Option Int
  area : Option Int
  buildings : Option Int
  evacuation : Bool
  deriving Repr, DecidableEq

/-- Association owns identity and source selection; metadata stays attached to it. -/
def attach (fires : List Fire) (scores : List Score)
    (association : Nat × RankedViews.Score) : Row :=
  let fire := fires.find? (fun item => item.identity.owner == association.1)
  let source := scores.find? (fun item => item.ranked.serial == association.2.serial)
  { owner := association.1
    name := (fire.map (·.identity.name)).getD association.2.name
    score := association.2.value
    serial := association.2.serial
    active := (fire.map Fire.active).getD false
    discovery := fire.bind Fire.discovery
    area := source.bind Score.area
    buildings := source.bind Score.buildings
    evacuation := (source.map Score.evacuation).getD false }

def resolved (fires : List Fire) (scores : List Score) : List Row :=
  (RankedViews.associations (fires.map Fire.identity) (scores.map Score.ranked)).map
    (attach fires scores)

theorem resolved_owners_are_unique (fires : List Fire) (scores : List Score) :
    ((resolved fires scores).map Row.owner).Nodup := by
  simpa [resolved, List.map_map, attach, Function.comp_def] using
    RankedViews.association_owners_are_unique
      (fires.map Fire.identity) (scores.map Score.ranked)

theorem resolved_retains_selected_source (fires : List Fire) (scores : List Score)
    (row : Row) (member : row ∈ resolved fires scores) :
    ∃ source ∈ scores,
      source.ranked.serial = row.serial ∧ source.ranked.value = row.score := by
  obtain ⟨⟨owner, score⟩, chosen, same⟩ := List.mem_map.mp member
  have source := (RankedViews.associated_score_retains_exact_source
    (fires.map Fire.identity) (scores.map Score.ranked) owner score chosen).1
  obtain ⟨item, belongs, equal⟩ := List.mem_map.mp source
  subst row
  exact ⟨item, belongs, by simp [attach, equal], by simp [attach, equal]⟩

/-- The default top fifth uses exact ceiling division, including tiny populations. -/
def topCount (count : Nat) : Nat := (count + 4) / 5

theorem top_count_is_exact_ceiling (count : Nat) :
    count ≤ 5 * topCount count ∧ 5 * topCount count < count + 5 := by
  unfold topCount
  omega

theorem nonempty_top_count_bounds (count : Nat) (positive : 0 < count) :
    0 < topCount count ∧ topCount count ≤ count := by
  unfold topCount
  omega

def activeScores (rows : List Row) : List Int :=
  ((rows.filter Row.active).map Row.score).mergeSort (fun a b => decide (b ≤ a))

theorem active_scores_membership (rows : List Row) (value : Int) :
    value ∈ activeScores rows ↔
      ∃ row ∈ rows, row.active = true ∧ row.score = value := by
  simp only [activeScores, List.mem_mergeSort, List.mem_map, List.mem_filter]
  constructor
  · rintro ⟨row, ⟨member, active⟩, same⟩
    exact ⟨row, member, active, same⟩
  · rintro ⟨row, member, active, same⟩
    exact ⟨row, ⟨member, active⟩, same⟩

theorem active_scores_descend (rows : List Row) :
    (activeScores rows).Pairwise (fun a b => b ≤ a) := by
  apply List.Pairwise.imp (fun {_ _} relation => of_decide_eq_true relation)
  apply List.pairwise_mergeSort
  · intro a b c first second
    simp only [decide_eq_true_eq] at *
    omega
  · intro a b
    simp only [Bool.or_eq_true, decide_eq_true_eq]
    omega

def threshold (rows : List Row) : Option Int :=
  let values := activeScores rows
  values[topCount values.length - 1]?

theorem threshold_missing_iff_no_active_scores (rows : List Row) :
    threshold rows = none ↔ activeScores rows = [] := by
  rw [threshold, List.getElem?_eq_none_iff, ← List.length_eq_zero_iff]
  have bounds := nonempty_top_count_bounds (activeScores rows).length
  constructor
  · intro absent
    by_cases nonzero : (activeScores rows).length = 0
    · exact nonzero
    · have := bounds (by omega)
      omega
  · intro empty
    simp [empty, topCount]

/-- The cutoff partitions the complete active population at the exact ceiling rank.
    Equal scores may occur on either side; the later inclusive gate retains them. -/
theorem threshold_partition (rows : List Row) (cutoff : Int)
    (chosen : threshold rows = some cutoff) :
    ∃ before after,
      activeScores rows = before ++ cutoff :: after ∧
      before.length + 1 = topCount (activeScores rows).length ∧
      (∀ value ∈ before, cutoff ≤ value) ∧
      (∀ value ∈ after, value ≤ cutoff) := by
  obtain ⟨bound, same⟩ := List.getElem?_eq_some_iff.mp chosen
  let index := topCount (activeScores rows).length - 1
  have decomposition : activeScores rows =
      (activeScores rows).take index ++
        cutoff :: (activeScores rows).drop (index + 1) := by
    rw [← same, ← List.drop_eq_getElem_cons bound]
    exact (List.take_append_drop index (activeScores rows)).symm
  have ordering := active_scores_descend rows
  rw [decomposition] at ordering
  obtain ⟨_, tailOrdered, cross⟩ := List.pairwise_append.mp ordering
  refine ⟨_, _, decomposition, ?_, ?_, ?_⟩
  · rw [List.length_take, Nat.min_eq_left (by omega)]
    have positive := nonempty_top_count_bounds (activeScores rows).length (by omega)
    dsimp [index]
    omega
  · intro value member
    exact cross value member cutoff (by simp)
  · exact (List.pairwise_cons.mp tailOrdered).1

def signals (row : Row) : Bool :=
  match row.area with
  | none => false
  | some area => decide (100 ≤ area) &&
    (decide (1000 ≤ area) || row.evacuation ||
      (row.buildings.map (fun count => decide (100 ≤ count))).getD false)

theorem signals_require_minimum_area (row : Row) (qualifies : signals row = true) :
    ∃ area, row.area = some area ∧ 100 ≤ area := by
  cases area : row.area with
  | none => simp [signals, area] at qualifies
  | some value =>
    refine ⟨value, rfl, ?_⟩
    simp only [signals, area, Bool.and_eq_true, decide_eq_true_eq] at qualifies
    exact qualifies.1

def eligible (now cutoff : Int) (row : Row) : Bool :=
  (row.discovery.map fun time => RankedViews.inWindow now 432000 time).getD false &&
    (decide (cutoff ≤ row.score) || signals row)

def precedes (first second : Row) : Bool :=
  decide (second.score < first.score ∨
    (first.score = second.score ∧ first.name ≤ second.name))

def select (now : Option Int) (rows : List Row) : List Row :=
  match now, threshold rows with
  | some time, some cutoff =>
    (rows.filter (eligible time cutoff)).mergeSort precedes
  | _, _ => []

def complete (now : Option Int) (fires : List Fire) (scores : List Score) : List Row :=
  select now (resolved fires scores)

theorem selection_is_exact (now : Int) (rows : List Row) (row : Row) :
    row ∈ select (some now) rows ↔
      ∃ cutoff time, threshold rows = some cutoff ∧ row ∈ rows ∧
        row.discovery = some time ∧ now - 432000 ≤ time ∧ time ≤ now ∧
        (cutoff ≤ row.score ∨ signals row = true) := by
  cases chosen : threshold rows with
  | none => simp [select, chosen]
  | some cutoff =>
    cases dated : row.discovery with
    | none => simp [select, chosen, eligible, dated]
    | some time =>
      simp [select, chosen, eligible, dated, RankedViews.inWindow, and_assoc]

theorem complete_selection_retains_source (now : Int) (fires : List Fire)
    (scores : List Score) (row : Row)
    (selected : row ∈ complete (some now) fires scores) :
    ∃ source ∈ scores,
      source.ranked.serial = row.serial ∧ source.ranked.value = row.score := by
  obtain ⟨_, _, _, member, _⟩ := selection_is_exact now _ row |>.mp selected
  exact resolved_retains_selected_source fires scores row member

theorem score_ties_qualify (now : Int) (rows : List Row) (row : Row) (time cutoff : Int)
    (member : row ∈ rows) (chosen : threshold rows = some cutoff)
    (dated : row.discovery = some time) (past : time ≤ now)
    (recent : now - 432000 ≤ time) (tied : row.score = cutoff) :
    row ∈ select (some now) rows := by
  exact (selection_is_exact now rows row).mpr
    ⟨cutoff, time, chosen, member, dated, recent, past, Or.inl (by omega)⟩

theorem signals_can_qualify_below_cutoff (now : Int) (rows : List Row) (row : Row)
    (time cutoff : Int) (member : row ∈ rows) (chosen : threshold rows = some cutoff)
    (dated : row.discovery = some time) (past : time ≤ now)
    (recent : now - 432000 ≤ time) (qualifies : signals row = true) :
    row ∈ select (some now) rows := by
  exact (selection_is_exact now rows row).mpr
    ⟨cutoff, time, chosen, member, dated, recent, past, Or.inr qualifies⟩

theorem future_discoveries_excluded (now : Int) (rows : List Row) (row : Row)
    (time : Int) (dated : row.discovery = some time) (future : now < time) :
    row ∉ select (some now) rows := by
  intro selected
  obtain ⟨_, recorded, _, _, same, _, past, _⟩ :=
    (selection_is_exact now rows row).mp selected
  have equal : recorded = time := Option.some.inj (same.symm.trans dated)
  omega

theorem threshold_ignores_inactive_rows (rows : List Row) :
    threshold (rows.filter Row.active) = threshold rows := by
  simp [threshold, activeScores, List.filter_filter]

theorem selected_owners_unique (now : Option Int) (rows : List Row)
    (unique : (rows.map Row.owner).Nodup) :
    ((select now rows).map Row.owner).Nodup := by
  cases now <;> cases chosen : threshold rows <;> simp only [select, chosen]
  all_goals try simp
  apply ((List.mergeSort_perm _ _).map Row.owner).nodup_iff.mpr
  exact (List.filter_sublist.map Row.owner).nodup unique

theorem complete_owners_unique (now : Option Int) (fires : List Fire)
    (scores : List Score) :
    ((complete now fires scores).map Row.owner).Nodup :=
  selected_owners_unique now _ (resolved_owners_are_unique fires scores)

theorem selection_ranked (now : Option Int) (rows : List Row) :
    (select now rows).Pairwise (fun a b => precedes a b = true) := by
  cases now <;> cases chosen : threshold rows <;> simp only [select, chosen]
  all_goals try simp
  apply List.pairwise_mergeSort
  · intro a b c first second
    simp only [precedes, decide_eq_true_eq] at *
    omega
  · intro a b
    simp only [precedes, Bool.or_eq_true, decide_eq_true_eq]
    omega

end PeriScribe.NotableViews
