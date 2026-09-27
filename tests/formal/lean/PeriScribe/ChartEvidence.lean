import Std

namespace PeriScribe.ChartEvidence

structure Event where
  time : Int
  length : Option Int
  percent : Option Int
  deriving Repr, DecidableEq

structure State where
  length : Option Int := none
  percent : Option Int := none
  deriving Repr, DecidableEq

structure Estimate where
  time : Int
  length : Int
  percent : Int
  deriving Repr, DecidableEq

/-- Missing fields keep independent ledgers rather than erasing the other source. -/
def advance (state : State) (event : Event) : State :=
  ⟨event.length.or state.length, event.percent.or state.percent⟩

def emit (time : Int) (state : State) : List Estimate :=
  match state.length, state.percent with
  | some length, some percent => [⟨time, length, percent⟩]
  | _, _ => []

def run (state : State) : List Event → List Estimate
  | [] => []
  | event :: rest =>
    let next := advance state event
    emit event.time next ++ run next rest

/-- Searching the complete prefix backwards is an independent reference ledger. -/
def lastValue (field : Event → Option Int) (history : List Event) : Option Int :=
  history.reverse.findSome? field

def accumulated (initial : State) (history : List Event) : State :=
  ⟨(lastValue Event.length history).or initial.length,
    (lastValue Event.percent history).or initial.percent⟩

def reference (initial : State) (past : List Event) : List Event → List Estimate
  | [] => []
  | event :: rest =>
    let through := past ++ [event]
    emit event.time (accumulated initial through) ++ reference initial through rest

theorem last_value_append (field : Event → Option Int) (first second : List Event) :
    lastValue field (first ++ second) =
      (lastValue field second).or (lastValue field first) := by
  simp [lastValue, List.reverse_append, List.findSome?_append]

theorem independent_ledgers_agree_with_advance (initial : State)
    (history : List Event) (event : Event) :
    accumulated initial (history ++ [event]) =
      advance (accumulated initial history) event := by
  simp only [accumulated, advance]
  rw [last_value_append, last_value_append]
  cases length : event.length <;> cases percent : event.percent <;>
    simp [lastValue, length, percent]

theorem streaming_equals_complete_prefix_reference (initial : State)
    (past history : List Event) :
    run (accumulated initial past) history = reference initial past history := by
  induction history generalizing past with
  | nil => rfl
  | cons event rest induction =>
    simp only [run, reference, independent_ledgers_agree_with_advance]
    congr 1
    rw [← independent_ledgers_agree_with_advance, induction]

theorem empty_prefix_agrees (history : List Event) :
    run {} history = reference {} [] history := by
  simpa [accumulated, lastValue] using
    streaming_equals_complete_prefix_reference {} [] history

theorem last_value_has_support (field : Event → Option Int) (history : List Event)
    (value : Int) (selected : lastValue field history = some value) :
    ∃ event ∈ history, field event = some value := by
  obtain ⟨before, event, after, decomposition, supplied, _⟩ :=
    List.findSome?_eq_some_iff.mp selected
  refine ⟨event, ?_, supplied⟩
  have member : event ∈ history.reverse := by rw [decomposition]; simp
  simpa using member

/-- The reference's source is the final supplying event, not merely an equal value. -/
theorem last_value_has_no_later_replacement (field : Event → Option Int)
    (history : List Event) (value : Int)
    (selected : lastValue field history = some value) :
    ∃ before event after, history = before ++ event :: after ∧
      field event = some value ∧ ∀ later ∈ after, field later = none := by
  obtain ⟨after, event, before, decomposition, supplied, absent⟩ :=
    List.findSome?_eq_some_iff.mp selected
  refine ⟨before.reverse, event, after.reverse, ?_, supplied, ?_⟩
  · have reversed := congrArg List.reverse decomposition
    simpa [List.reverse_append, List.reverse_cons, List.append_assoc] using reversed
  · intro later member
    exact absent later (by simpa using member)

theorem last_value_is_chronologically_latest (field : Event → Option Int)
    (history : List Event) (value : Int)
    (ordered : history.Pairwise (fun a b => a.time ≤ b.time))
    (selected : lastValue field history = some value) :
    ∃ source ∈ history, field source = some value ∧
      ∀ candidate ∈ history, (field candidate).isSome = true →
        candidate.time ≤ source.time := by
  obtain ⟨before, source, after, decomposition, supplied, absent⟩ :=
    last_value_has_no_later_replacement field history value selected
  refine ⟨source, by rw [decomposition]; simp, supplied, ?_⟩
  intro candidate member known
  rw [decomposition] at member ordered
  rcases List.mem_append.mp member with earlier | later
  · exact (List.pairwise_append.mp ordered).2.2 candidate earlier source (by simp)
  · rcases List.mem_cons.mp later with same | belongs
    · subst candidate; omega
    · simp [absent candidate belongs] at known

theorem missing_fields_cannot_erase_evidence (state : State) (event : Event)
    (lengthMissing : event.length = none) (percentMissing : event.percent = none) :
    advance state event = state := by cases state; simp [advance, lengthMissing,
      percentMissing]

theorem emitted_estimates_need_both_sources (time : Int) (state : State)
    (estimate : Estimate) (member : estimate ∈ emit time state) :
    estimate.time = time ∧ state.length = some estimate.length ∧
      state.percent = some estimate.percent := by
  cases length : state.length <;> cases percent : state.percent <;>
    simp [emit, length, percent] at member
  subst estimate
  simp

theorem run_append (state : State) (first second : List Event) :
    run state (first ++ second) =
      run state first ++ run (accumulated state first) second := by
  induction first generalizing state with
  | nil => simp [run, accumulated, lastValue]
  | cons event rest induction =>
    simp only [List.cons_append, run, induction, List.append_assoc]
    congr 2
    simp only [accumulated, lastValue, List.reverse_cons, List.findSome?_append,
      List.findSome?_cons, List.findSome?_nil, advance]
    cases rest.reverse.findSome? Event.length <;>
      cases rest.reverse.findSome? Event.percent <;>
      cases event.length <;> cases event.percent <;> rfl

theorem appended_events_cannot_rewrite_prior_estimates (state : State)
    (first second : List Event) :
    (run state first).IsPrefix (run state (first ++ second)) :=
  ⟨run (accumulated state first) second, (run_append state first second).symm⟩

/-- Duplicate source times have an explicit last-input-wins boundary. -/
def exactAt (time : Int) (history : List (Int × Int)) : Option Int :=
  ((history.reverse.find? (fun event => event.1 == time)).map Prod.snd)

def timeline (lengths percents : List (Int × Int)) : List Event :=
  let times := ((lengths.map Prod.fst ++ percents.map Prod.fst).eraseDups).mergeSort
    (fun a b => decide (a ≤ b))
  times.map fun time => ⟨time, exactAt time lengths, exactAt time percents⟩

def estimates (lengths percents : List (Int × Int)) : List Estimate :=
  run {} (timeline lengths percents)

theorem timeline_has_exact_event_times (lengths percents : List (Int × Int))
    (time : Int) : time ∈ (timeline lengths percents).map Event.time ↔
      time ∈ lengths.map Prod.fst ∨ time ∈ percents.map Prod.fst := by
  simp [timeline, List.map_map, Function.comp_def]

theorem timeline_is_chronological (lengths percents : List (Int × Int)) :
    (timeline lengths percents).Pairwise (fun a b => a.time ≤ b.time) := by
  rw [timeline, List.pairwise_map]
  apply List.Pairwise.imp (fun {_ _} relation => of_decide_eq_true relation)
  apply List.pairwise_mergeSort
  · intro a b c first second
    simp only [decide_eq_true_eq] at *
    omega
  · intro a b
    simp only [Bool.or_eq_true, decide_eq_true_eq]
    omega

theorem timeline_times_are_unique (lengths percents : List (Int × Int)) :
    ((timeline lengths percents).map Event.time).Nodup := by
  simp only [timeline, List.map_map, Function.comp_def]
  rw [List.map_id']
  apply (List.mergeSort_perm _ _).nodup_iff.mpr
  have unique : ∀ values : List Int, values.eraseDups.Nodup := by
    intro values
    induction bound : values.length using Nat.strongRecOn generalizing values with
    | ind count induction =>
      cases values with
      | nil => simp
      | cons first rest =>
        rw [List.eraseDups_cons, List.nodup_cons]
        constructor
        · simp [List.mem_eraseDups]
        · apply induction _ _ _ rfl
          have := List.length_filter_le (fun value => !value == first) rest
          simp only [List.length_cons] at bound
          omega
  exact unique _

structure Point where
  identity : Nat
  time : Int
  value : Int
  dashed : Bool
  deriving Repr, DecidableEq

structure Edge where
  first : Point
  second : Point
  deriving Repr, DecidableEq

def edges : List Point → List Edge
  | [] => []
  | [_] => []
  | first :: second :: rest => ⟨first, second⟩ :: edges (second :: rest)

structure Segment where
  dashed : Bool
  edges : List Edge
  deriving Repr, DecidableEq

/-- Grouping whole edges makes source connectivity an explicit conserved quantity. -/
def group : List Edge → List Segment
  | [] => []
  | edge :: rest =>
    match group rest with
    | [] => [⟨edge.second.dashed, [edge]⟩]
    | segment :: segments =>
      if edge.second.dashed = segment.dashed then
        { segment with edges := edge :: segment.edges } :: segments
      else ⟨edge.second.dashed, [edge]⟩ :: segment :: segments

def flattened (segments : List Segment) : List Edge := segments.flatMap Segment.edges

theorem grouping_preserves_every_edge_in_order (source : List Edge) :
    flattened (group source) = source := by
  induction source with
  | nil => rfl
  | cons edge rest induction =>
    cases grouped : group rest with
    | nil => simpa [group, flattened, grouped] using congrArg (List.cons edge) induction
    | cons segment segments =>
      rw [group, grouped]
      dsimp only
      split <;> simpa [flattened, grouped, List.append_assoc] using
        congrArg (List.cons edge) induction

theorem grouping_has_nonempty_homogeneous_segments (source : List Edge)
    (segment : Segment) (member : segment ∈ group source) :
    segment.edges ≠ [] ∧
      ∀ edge ∈ segment.edges, edge.second.dashed = segment.dashed := by
  induction source generalizing segment with
  | nil => simp [group] at member
  | cons edge rest induction =>
    simp only [group] at member
    cases grouped : group rest with
    | nil =>
      simp only [grouped, List.mem_singleton] at member
      subst segment
      simp
    | cons next remaining =>
      simp only [grouped] at member
      split at member
      · rename_i same
        rcases List.mem_cons.mp member with changed | later
        · subst segment
          have old := induction next (by simp [grouped])
          exact ⟨by simp, by simpa using And.intro same old.2⟩
        · exact induction segment (by simp [grouped, later])
      · rcases List.mem_cons.mp member with first | later
        · subst segment; simp
        · exact induction segment (by simpa [grouped] using later)

def segments (points : List Point) : List Segment := group (edges points)

def legend (points : List Point) : List Bool :=
  [false, true].filter fun style => (edges points).any (fun edge =>
    edge.second.dashed == style)

theorem segments_preserve_all_source_edges (points : List Point) :
    flattened (segments points) = edges points :=
  grouping_preserves_every_edge_in_order _

theorem legend_exactly_describes_edges (points : List Point) (style : Bool) :
    style ∈ legend points ↔ ∃ edge ∈ edges points, edge.second.dashed = style := by
  cases style <;> simp [legend, List.any_eq_true]

theorem legend_exactly_describes_rendered_segments
    (points : List Point) (style : Bool) :
    style ∈ legend points ↔ ∃ segment ∈ segments points, segment.dashed = style := by
  rw [legend_exactly_describes_edges, ← segments_preserve_all_source_edges]
  constructor
  · rintro ⟨edge, belongs, same⟩
    obtain ⟨segment, member, inSegment⟩ := List.mem_flatMap.mp belongs
    have correct := grouping_has_nonempty_homogeneous_segments _ _ member
    exact ⟨segment, member, (correct.2 edge inSegment).symm.trans same⟩
  · rintro ⟨segment, member, same⟩
    obtain ⟨nonempty, correct⟩ := grouping_has_nonempty_homogeneous_segments _ _ member
    obtain ⟨edge, belongs⟩ := List.exists_mem_of_ne_nil _ nonempty
    exact ⟨edge, List.mem_flatMap.mpr ⟨segment, member, belongs⟩,
      (correct edge belongs).trans same⟩

theorem isolated_point_has_no_segment_or_legend (point : Point) :
    segments [point] = [] ∧ legend [point] = [] := by
  simp [segments, edges, group, legend]

end PeriScribe.ChartEvidence
