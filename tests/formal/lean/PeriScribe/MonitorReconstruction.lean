import Std

namespace PeriScribe.MonitorReconstruction

abbrev Path := List Nat

inductive Kind where
  | commandStart | phaseStart | phaseFinish | commandFinish
  | ordinary | skipped | planned
  deriving DecidableEq, Repr

inductive Status where
  | waiting | active | completed | failed | stopped
  deriving DecidableEq, Repr

structure Event where
  owner : Nat
  kind : Kind
  explicit : Option Path := none
  phase : Option Nat := none
  failed : Bool := false
  deriving DecidableEq, Repr

structure Run where
  path : Path := []
  status : Status := .active
  deriving DecidableEq, Repr

def eventPath (run : Run) (event : Event) : Path :=
  match event.explicit with
  | some path => path
  | none => match event.phase with
    | none => run.path
    | some phase =>
      if event.kind = .phaseFinish ∧ run.path ≠ [] then run.path
      else run.path ++ [phase]

def stepRun (run : Run) (event : Event) : Run :=
  match event.kind with
  | .commandStart => { run with path := [] }
  | .phaseStart => { run with path := eventPath run event }
  | .phaseFinish => { run with path := (eventPath run event).dropLast }
  | .commandFinish => ⟨[], if event.failed then .failed else .completed⟩
  | _ => run

abbrev State := Nat → Run

def step (state : State) (event : Event) : State :=
  fun owner => if owner = event.owner then stepRun (state owner) event else state owner

def process (state : State) (events : List Event) : State := events.foldl step state

theorem unrelated_run_unchanged (state : State) (event : Event) (owner : Nat)
    (different : owner ≠ event.owner) : step state event owner = state owner := by
  simp [step, different]

theorem owner_uses_own_context (state : State) (event : Event) :
    step state event event.owner = stepRun (state event.owner) event := by simp [step]

theorem interleaved_runs_commute (state : State) (first second : Event)
    (different : first.owner ≠ second.owner) :
    step (step state first) second = step (step state second) first := by
  funext owner
  simp only [step]
  split <;> split <;> simp_all

theorem batch_stream_equivalent (state : State) (first second : List Event) :
    process state (first ++ second) = process (process state first) second := by
  simp [process, List.foldl_append]

theorem run_history_isolated (state : State) (events : List Event) (owner : Nat) :
    process state events owner =
      (events.filter (fun event => event.owner == owner)).foldl
        stepRun (state owner) := by
  induction events generalizing state with
  | nil => rfl
  | cons first rest induction =>
    simp only [process, List.foldl_cons]
    rw [show rest.foldl step (step state first) owner = _ from
      induction (step state first)]
    by_cases same : owner = first.owner
    · simp [step, same]
    · have reverse : first.owner ≠ owner := Ne.symm same
      simp [step, same, reverse]

/-- An ordinary message cannot turn a run into a completed or failed command. -/
theorem ordinary_preserves_outcome (run : Run) (event : Event)
    (ordinary : event.kind = .ordinary) : (stepRun run event).status = run.status := by
  simp [stepRun, ordinary]

def isPrefix (a b : Path) : Bool := a == b.take a.length

def phaseStep (path : Path) (status : Status) (event : Kind × Path × Bool) : Status :=
  let observed :=
    if status = .waiting ∧ isPrefix path event.2.1 then .active else status
  if event.2.1 = path ∧ path ≠ [] then
    match event.1 with
    | .phaseStart => .active
    | .phaseFinish => if event.2.2 then .failed else .completed
    | _ => observed
  else observed

def phaseStatus (path : Path) (events : List (Kind × Path × Bool)) : Status :=
  events.foldl (phaseStep path) .waiting

def completionWitness (path : Path) (failed : Bool)
    (event : Kind × Path × Bool) : Prop :=
  event.1 = .phaseFinish ∧ event.2.1 = path ∧ path ≠ [] ∧ event.2.2 = failed

theorem completed_step_has_evidence (path : Path) (before : Status)
    (event : Kind × Path × Bool)
    (completed : phaseStep path before event = .completed) :
    before = .completed ∨ completionWitness path false event := by
  rcases event with ⟨kind, observed, failed⟩
  cases kind <;> cases failed <;> simp_all [phaseStep, completionWitness] <;> grind

theorem failed_step_has_evidence (path : Path) (before : Status)
    (event : Kind × Path × Bool) (failed : phaseStep path before event = .failed) :
    before = .failed ∨ completionWitness path true event := by
  rcases event with ⟨kind, observed, failure⟩
  cases kind <;> cases failure <;> simp_all [phaseStep, completionWitness] <;> grind

theorem completed_history_has_evidence (path : Path)
    (events : List (Kind × Path × Bool)) (before : Status)
    (completed : events.foldl (phaseStep path) before = .completed) :
    before = .completed ∨ ∃ event ∈ events, completionWitness path false event := by
  induction events generalizing before with
  | nil => exact Or.inl completed
  | cons first rest induction =>
    simp only [List.foldl_cons] at completed
    rcases induction _ completed with prior | ⟨event, present, witness⟩
    · rcases completed_step_has_evidence path before first prior with initial | witness
      · exact Or.inl initial
      · exact Or.inr ⟨first, by simp, witness⟩
    · exact Or.inr ⟨event, by simp [present], witness⟩

theorem failed_history_has_evidence (path : Path)
    (events : List (Kind × Path × Bool)) (before : Status)
    (failed : events.foldl (phaseStep path) before = .failed) :
    before = .failed ∨ ∃ event ∈ events, completionWitness path true event := by
  induction events generalizing before with
  | nil => exact Or.inl failed
  | cons first rest induction =>
    simp only [List.foldl_cons] at failed
    rcases induction _ failed with prior | ⟨event, present, witness⟩
    · rcases failed_step_has_evidence path before first prior with initial | witness
      · exact Or.inl initial
      · exact Or.inr ⟨first, by simp, witness⟩
    · exact Or.inr ⟨event, by simp [present], witness⟩

def outcome : Status → Option Bool
  | .completed => some false
  | .failed => some true
  | _ => none

theorem ordinary_preserves_phase_outcome (path observed : Path) (before : Status)
    (failed : Bool) :
    outcome (phaseStep path before (.ordinary, observed, failed)) = outcome before := by
  cases before <;> simp [phaseStep, outcome]
  split <;> split at * <;> simp_all

theorem phase_step_respects_outcome (path : Path) (before after : Status)
    (event : Kind × Path × Bool) (same : outcome before = outcome after) :
    outcome (phaseStep path before event) = outcome (phaseStep path after event) := by
  cases before <;> cases after <;> simp_all [outcome] <;> grind [phaseStep, outcome]

/-- Omission codes keep explicit decisions separate from inferred absent execution. -/
def omission (run : Status) (explicitSkip : Bool) (parents : List Status) : Nat :=
  if explicitSkip then 1
  else if run = .failed then 2
  else if run ≠ .active then 3
  else match parents.find?
      (fun parent => parent == .completed || parent == .failed) with
    | some .completed => 4
    | some .failed => 5
    | _ => 0

def displayed (run phase : Status) : Status :=
  if run ≠ .active ∧ phase = .active then .stopped else phase

theorem skip_requires_explicit_decision (run : Status) (explicitSkip : Bool)
    (parents : List Status) : omission run explicitSkip parents = 1 ↔ explicitSkip := by
  cases explicitSkip <;> simp [omission] <;> grind

theorem missing_is_not_completed (run : Status) :
    displayed run .waiting ≠ .completed := by
  simp [displayed]

theorem unfinished_is_not_success (run : Status) (terminal : run ≠ .active) :
    displayed run .active = .stopped := by simp [displayed, terminal]

def structural (event : Kind × Path × Bool) : Bool := event.1 != .ordinary

/-- Retention removes only ordinary rows before the retained suffix. -/
def retained (limit : Nat) (events : List (Kind × Path × Bool)) :
    List (Kind × Path × Bool) :=
  (events.zipIdx.filter fun (event, index) =>
    structural event || events.length - limit ≤ index).map (·.1)

/-- Every structural observation survives, in its original order and multiplicity. -/
theorem structural_evidence_preserved (limit : Nat)
    (events : List (Kind × Path × Bool)) :
    (retained limit events).filter structural = events.filter structural := by
  unfold retained
  rw [List.filter_map]
  rw [List.filter_filter]
  have equal : (fun item : (Kind × Path × Bool) × Nat =>
      structural item.1 && (structural item.1 ||
        decide (events.length - limit ≤ item.2))) =
      (fun item => structural item.1) := by
    funext item
    cases structural item.1 <;> simp
  change ((events.zipIdx.filter fun item => structural item.1 &&
    (structural item.1 || decide (events.length - limit ≤ item.2))).map (·.1)) = _
  rw [equal]
  change List.map Prod.fst (List.filter (structural ∘ Prod.fst) events.zipIdx) = _
  rw [← List.filter_map]
  simp

theorem structural_history_preserves_outcome (path : Path)
    (events : List (Kind × Path × Bool)) (before after : Status)
    (same : outcome before = outcome after) :
    outcome (events.foldl (phaseStep path) before) =
      outcome ((events.filter structural).foldl (phaseStep path) after) := by
  induction events generalizing before after with
  | nil => exact same
  | cons first rest induction =>
    simp only [List.foldl_cons, List.filter_cons]
    by_cases ordinary : first.1 = .ordinary
    · have preserved : outcome (phaseStep path before first) = outcome after := by
        rcases first with ⟨kind, observed, failed⟩
        simp only at ordinary
        subst kind
        exact (ordinary_preserves_phase_outcome path observed before failed).trans same
      simpa [structural, ordinary] using induction _ _ preserved
    · have preserved := phase_step_respects_outcome path before after first same
      simpa [structural, ordinary] using induction _ _ preserved

theorem retained_completion_and_failure (path : Path) (limit : Nat)
    (events : List (Kind × Path × Bool)) :
    outcome (phaseStatus path (retained limit events)) =
      outcome (phaseStatus path events) := by
  unfold phaseStatus
  rw [structural_history_preserves_outcome path (retained limit events)
      .waiting .waiting rfl]
  rw [structural_evidence_preserved]
  exact (structural_history_preserves_outcome path events .waiting .waiting rfl).symm

/-- Command retention bounds run count; older evicted runs need archive restoration. -/
def retainedRuns (limit : Nat) (runs : List Nat) : List Nat :=
  runs.drop (runs.length - limit)

theorem run_retention_bounded (limit : Nat) (runs : List Nat) :
    (retainedRuns limit runs).length ≤ limit := by
  simp [retainedRuns]
  omega

end PeriScribe.MonitorReconstruction
