import PeriScribe.AreaPolicy

namespace PeriScribe.AreaHistory

structure Evidence where
  time : Nat
  area : Nat
  provenance : Nat
  deriving DecidableEq, Repr

structure Mapping where
  evidence : Evidence
  surveyed : Bool
  deriving Repr

structure Report where
  evidence : Evidence
  confirmation : Option Nat
  confirmed : Bool
  deriving Repr

structure Estimate where
  time : Nat
  evidence : Evidence
  reported : Bool
  deriving DecidableEq, Repr

structure State where
  fresh : Option Mapping := none
  baseline : Option Nat := none
  reports : List Report := []
  selected : Option Estimate := none
  deriving Repr

structure Event where
  time : Nat
  mapping : Option Mapping := none
  report : Option Report := none
  deriving Repr

/-- A recursive last lookup preserves the whole source record, including provenance. -/
def last? {Value : Type} : List Value → Option Value
  | [] => none
  | first :: rest => (last? rest).or (some first)

theorem last_is_member {Value : Type} (values : List Value) (value : Value)
    (selected : last? values = some value) : value ∈ values := by
  induction values with
  | nil => simp [last?] at selected
  | cons first rest induction =>
    simp only [last?] at selected
    cases previous : last? rest with
    | none => simp [previous] at selected; simp [selected]
    | some other =>
      simp [previous] at selected
      subst other
      exact List.mem_cons_of_mem _ (induction previous)

/-- Only accepted reports participate in both baselines and rapid confirmations. -/
def accept (accepted : List Report) (report : Report) : List Report :=
  match last? accepted with
  | none => accepted ++ [report]
  | some previous =>
    if AreaPolicy.acceptReport previous.evidence.area report.evidence.area
        report.confirmed then accepted ++ [report] else accepted

def accepted (reports : List Report) : List Report := reports.foldl accept []

def takeover (mapping : Mapping) (reports : List Report) (time : Nat)
    (baseline : Option Nat) : Bool :=
  match last? reports with
  | none => false
  | some report =>
    let confirmations := (reports.filterMap fun candidate =>
      if candidate.confirmed && mapping.evidence.time < candidate.evidence.time &&
          2 * mapping.evidence.area ≤ candidate.evidence.area
      then some candidate.confirmation else none).eraseDups.length
    AreaPolicy.takeover ⟨mapping.evidence.area, report.evidence.area,
      decide (mapping.evidence.time < report.evidence.time), baseline,
      (time : Int) - mapping.evidence.time, confirmations⟩

/-- A fresh survey resets ownership even after reports supplied the selected acreage. -/
def mappingSelection (selected : Option Estimate) (mapping : Option Mapping)
    (time : Nat) : Option Estimate :=
  match mapping with
  | none => selected
  | some observation =>
    if observation.surveyed || selected.isNone ||
        (selected.isSome && !(selected.getD ⟨0, ⟨0, 0, 0⟩, false⟩).reported)
    then some ⟨time, observation.evidence, false⟩ else selected

/-- Reporting persists between surveys while retaining each selected source record. -/
def reportSelection (selected : Option Estimate) (reports : List Report)
    (permitted : Bool) (time : Nat) : Option Estimate :=
  match last? reports with
  | some report => if permitted then some ⟨time, report.evidence, true⟩ else selected
  | none => selected

/-- One event represents an observation time or an inserted policy deadline. -/
def step (state : State) (event : Event) : State :=
  let reports := state.reports ++ event.report.toList
  let fresh := match event.mapping with
    | some mapping => if mapping.surveyed then some mapping else state.fresh
    | none => state.fresh
  let baseline := match event.mapping with
    | some mapping => if mapping.surveyed
        then (last? reports).map (fun report => report.evidence.area)
        else state.baseline
    | none => state.baseline
  let mapped := mappingSelection state.selected event.mapping event.time
  let permitted := match fresh with
    | none => true
    | some mapping => (mapped.isSome && (mapped.getD ⟨0, ⟨0, 0, 0⟩, false⟩).reported) ||
        takeover mapping reports event.time baseline
  let selected := reportSelection mapped reports permitted event.time
  ⟨fresh, baseline, reports,
    selected.map (fun estimate => { estimate with time := event.time })⟩

/-- Separate effective times let deadline estimates retain their older evidence. -/
def run (state : State) : List Event → List Estimate
  | [] => []
  | event :: rest =>
    let next := step state event
    next.selected.toList ++ run next rest

def Supports (predicate : Evidence → Prop) (selected : Option Estimate) : Prop :=
  ∀ estimate, selected = some estimate → predicate estimate.evidence

theorem mapping_selection_preserves_evidence (predicate : Evidence → Prop)
    (selected : Option Estimate) (mapping : Option Mapping) (time : Nat)
    (prior : Supports predicate selected)
    (observed : ∀ observation,
      mapping = some observation → predicate observation.evidence) :
    Supports predicate (mappingSelection selected mapping time) := by
  intro estimate chosen
  cases mapping with
  | none => exact prior estimate chosen
  | some observation =>
    simp only [mappingSelection] at chosen
    split at chosen
    · cases Option.some.inj chosen
      exact observed observation rfl
    · exact prior estimate chosen

theorem report_selection_preserves_evidence (predicate : Evidence → Prop)
    (selected : Option Estimate) (reports : List Report) (permitted : Bool) (time : Nat)
    (prior : Supports predicate selected)
    (observed : ∀ report ∈ reports, predicate report.evidence) :
    Supports predicate (reportSelection selected reports permitted time) := by
  intro estimate chosen
  simp only [reportSelection] at chosen
  cases latest : last? reports with
  | none => simp only [latest] at chosen; exact prior estimate chosen
  | some report =>
    simp only [latest] at chosen
    split at chosen
    · cases Option.some.inj chosen
      exact observed report (last_is_member reports report latest)
    · exact prior estimate chosen

theorem step_preserves_source_provenance (predicate : Evidence → Prop)
    (state : State) (event : Event)
    (prior : Supports predicate state.selected)
    (reports : ∀ report ∈ state.reports ++ event.report.toList,
      predicate report.evidence)
    (mapping : ∀ value, event.mapping = some value → predicate value.evidence) :
    Supports predicate (step state event).selected := by
  intro estimate chosen
  simp only [step] at chosen
  rcases Option.map_eq_some_iff.mp chosen with ⟨selected, selectedChoice, same⟩
  cases same
  exact report_selection_preserves_evidence predicate _ _ _ _
    (mapping_selection_preserves_evidence predicate _ _ _ prior mapping)
    reports selected selectedChoice

theorem step_assigns_current_effective_time (state : State) (event : Event)
    (estimate : Estimate) (selected : (step state event).selected = some estimate) :
    estimate.time = event.time := by
  simp only [step] at selected
  rcases Option.map_eq_some_iff.mp selected with ⟨chosen, _, same⟩
  cases same
  rfl

theorem selection_never_uses_future_evidence (state : State) (event : Event)
    (prior : Supports (fun evidence => evidence.time ≤ event.time) state.selected)
    (reports : ∀ report ∈ state.reports ++ event.report.toList,
      report.evidence.time ≤ event.time)
    (mapping : ∀ value, event.mapping = some value → value.evidence.time ≤ event.time) :
    Supports (fun evidence => evidence.time ≤ event.time) (step state event).selected :=
  step_preserves_source_provenance _ state event prior reports mapping

theorem fresh_mapping_resets_report_selection (prior : Option Estimate)
    (mapping : Mapping) (time : Nat) (fresh : mapping.surveyed = true) :
    mappingSelection prior (some mapping) time =
      some ⟨time, mapping.evidence, false⟩ := by
  simp [mappingSelection, fresh]

theorem fresh_survey_restores_mapped_history (state : State) (event : Event)
    (mapping : Mapping) (observed : event.mapping = some mapping)
    (fresh : mapping.surveyed = true) (dated : mapping.evidence.time = event.time) :
    (step state event).selected = some ⟨event.time, mapping.evidence, false⟩ := by
  cases latest : last? (state.reports ++ event.report.toList) with
  | none => simp [step, observed, fresh, mappingSelection, reportSelection, latest]
  | some report =>
    simp [step, observed, fresh, mappingSelection, reportSelection, takeover, latest,
      AreaPolicy.takeover, AreaPolicy.Eligible, dated]

/-- A fold can only select evidence supplied by its initial state or input events. -/
theorem run_preserves_source_provenance (predicate : Evidence → Prop)
    (state : State) (events : List Event)
    (prior : Supports predicate state.selected)
    (reports : ∀ report ∈ state.reports, predicate report.evidence)
    (observed : ∀ event ∈ events,
      (∀ mapping, event.mapping = some mapping → predicate mapping.evidence) ∧
      (∀ report, event.report = some report → predicate report.evidence)) :
    ∀ estimate ∈ run state events, predicate estimate.evidence := by
  induction events generalizing state with
  | nil => simp [run]
  | cons event rest induction =>
    have supplied := observed event (by simp)
    have known : ∀ report ∈ state.reports ++ event.report.toList,
        predicate report.evidence := by
      intro report member
      rcases List.mem_append.mp member with old | new
      · exact reports report old
      · exact supplied.2 report (by simpa using new)
    have selected := step_preserves_source_provenance predicate state event prior known
      supplied.1
    intro estimate member
    simp only [run, List.mem_append] at member
    rcases member with current | later
    · exact selected estimate (by simpa using current)
    · exact induction (step state event) selected known
        (fun next member => observed next (by simp [member])) estimate later

theorem run_estimates_have_event_times (state : State) (events : List Event)
    (estimate : Estimate) (member : estimate ∈ run state events) :
    ∃ event ∈ events, estimate.time = event.time := by
  induction events generalizing state with
  | nil => simp [run] at member
  | cons event rest induction =>
    simp only [run, List.mem_append] at member
    rcases member with current | later
    · exact ⟨event, by simp, step_assigns_current_effective_time state event estimate
        (by simpa using current)⟩
    · rcases induction (step state event) later with ⟨laterEvent, present, same⟩
      exact ⟨laterEvent, by simp [present], same⟩

/-- Every carried report and estimate stays causal throughout a chronological fold. -/
theorem run_never_uses_future_evidence (state : State) (events : List Event)
    (ordered : events.Pairwise (fun first second => first.time ≤ second.time))
    (initial : ∀ event ∈ events,
      Supports (fun evidence => evidence.time ≤ event.time) state.selected ∧
      ∀ report ∈ state.reports, report.evidence.time ≤ event.time)
    (observed : ∀ event ∈ events,
      (∀ mapping, event.mapping = some mapping → mapping.evidence.time ≤ event.time) ∧
      (∀ report, event.report = some report → report.evidence.time ≤ event.time)) :
    ∀ estimate ∈ run state events, estimate.evidence.time ≤ estimate.time := by
  induction events generalizing state with
  | nil => simp [run]
  | cons event rest induction =>
    have supplied := observed event (by simp)
    have ready := initial event (by simp)
    have ordering := List.pairwise_cons.mp ordered
    have known : ∀ report ∈ state.reports ++ event.report.toList,
        report.evidence.time ≤ event.time := by
      intro report member
      rcases List.mem_append.mp member with old | new
      · exact ready.2 report old
      · exact supplied.2 report (by simpa using new)
    have selected := selection_never_uses_future_evidence state event ready.1 known
      supplied.1
    intro estimate member
    simp only [run, List.mem_append] at member
    rcases member with current | later
    · have chosen : (step state event).selected = some estimate := by
        simpa using current
      rw [step_assigns_current_effective_time state event estimate chosen]
      exact selected estimate chosen
    · apply induction (step state event) ordering.2 ?_
        (fun next member => observed next (by simp [member])) estimate later
      intro next member
      have advancing := ordering.1 next member
      constructor
      · intro estimate chosen
        exact Nat.le_trans (selected estimate chosen) advancing
      · intro report present
        exact Nat.le_trans (known report present) advancing

/-- Last observation at a timestamp wins, matching the Python dictionaries. -/
def eventAt (mappings : List Mapping) (reports : List Report) (time : Nat) : Event :=
  ⟨time, last? (mappings.filter (fun mapping => mapping.evidence.time == time)),
    last? (reports.filter (fun report => report.evidence.time == time))⟩

/-- Deadlines are inserted within observed history without assuming future evidence. -/
def times (mappings : List Mapping) (reports : List Report) : List Nat :=
  let observed := mappings.map (fun mapping => mapping.evidence.time) ++
    reports.map (fun report => report.evidence.time)
  let lastTime := observed.foldl max 0
  let deadlines := mappings.flatMap (fun mapping =>
    [mapping.evidence.time + 86400, mapping.evidence.time + 259200])
  (observed ++ deadlines.filter (fun deadline => deadline ≤ lastTime))
    |>.eraseDups.mergeSort

def history (mappings : List Mapping) (reports : List Report) : List Estimate :=
  let acceptedReports := accepted reports
  run {} ((times mappings acceptedReports).map (eventAt mappings acceptedReports))

/-- Sorting is part of the executable history construction, not a caller assumption. -/
theorem history_never_uses_future_evidence (mappings : List Mapping)
    (reports : List Report) (estimate : Estimate)
    (member : estimate ∈ history mappings reports) :
    estimate.evidence.time ≤ estimate.time := by
  apply run_never_uses_future_evidence {} _ ?_ ?_ ?_ estimate member
  · apply List.pairwise_map.mpr
    simp only [eventAt]
    unfold times
    apply List.Pairwise.imp (fun {_ _} ordered => of_decide_eq_true ordered)
    apply List.pairwise_mergeSort
    · intro first middle last firstOrder secondOrder
      exact decide_eq_true (Nat.le_trans
        (of_decide_eq_true firstOrder) (of_decide_eq_true secondOrder))
    · intro first second
      simp only [Bool.or_eq_true, decide_eq_true_eq]
      omega

  · intro event present
    constructor
    · intro estimate impossible
      contradiction
    · simp
  · intro event present
    rcases List.mem_map.mp present with ⟨time, _, same⟩
    subst event
    constructor
    · intro mapping selected
      have found := last_is_member _ _ selected
      have dated := (List.mem_filter.mp found).2
      simpa [eventAt] using Nat.le_of_eq (of_decide_eq_true dated)
    · intro report selected
      have found := last_is_member _ _ selected
      have dated := (List.mem_filter.mp found).2
      simpa [eventAt] using Nat.le_of_eq (of_decide_eq_true dated)

end PeriScribe.AreaHistory
