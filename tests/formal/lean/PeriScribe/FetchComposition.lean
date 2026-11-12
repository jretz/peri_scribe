import PeriScribe.Pipeline

namespace PeriScribe.FetchComposition

/-- Collection joins before indexing, acknowledgment and prior-intent restoration. -/
structure Policy where
  full : Bool
  prior : Bool
  indexFailure : Bool
  deferIndex : Bool
  deriving DecidableEq, Repr

/-- The collection boundary retains partial writes even when a worker is fatal. -/
structure Collection where
  snapshots : Nat
  fatal : Bool
  sourceError : Bool
  deriving DecidableEq, Repr

/-- Snapshot sets use the same finite bit positions as the conformance transport. -/
structure Outcome where
  snapshots : Nat
  indexed : Nat
  pending : Bool
  acknowledged : Bool
  indexAttempted : Bool
  failed : Bool
  deriving DecidableEq, Repr

/-- Each phase changes only the fields owned by that phase. -/
def index (policy : Policy) (collection : Collection) : Outcome :=
  let attempted := !policy.deferIndex && (collection.snapshots != 0 || policy.full)
  { snapshots := collection.snapshots
    indexed := if attempted && !policy.indexFailure then collection.snapshots else 0
    pending := true
    acknowledged := false
    indexAttempted := attempted
    failed := (attempted && policy.indexFailure) || collection.sourceError }

/-- A failed index or source result prevents successful cadence acknowledgment. -/
def acknowledge (policy : Policy) (state : Outcome) : Outcome :=
  if state.failed then state
  else { state with acknowledged := policy.full && !policy.deferIndex }

/-- An unchanged successful incremental collection restores the captured intent. -/
def restore (policy : Policy) (state : Outcome) : Outcome :=
  if state.failed then state
  else if state.snapshots == 0 && !policy.full && !policy.deferIndex then
    { state with pending := policy.prior }
  else state

/-- Fatal collection skips all post-join success phases without discarding writes. -/
def execute (policy : Policy) (collection : Collection) : Outcome :=
  if collection.fatal then
    { snapshots := collection.snapshots
      indexed := 0
      pending := true
      acknowledged := false
      indexAttempted := false
      failed := true }
  else restore policy (acknowledge policy (index policy collection))

/-- This closed projection is compared independently with the complete TLC relation. -/
def projected (policy : Policy) (collection : Collection) : Outcome :=
  let attempted := !collection.fatal && !policy.deferIndex &&
    (collection.snapshots != 0 || policy.full)
  let failed := collection.fatal || (attempted && policy.indexFailure) ||
    (!collection.fatal && collection.sourceError)
  { snapshots := collection.snapshots
    indexed := if attempted && !policy.indexFailure then collection.snapshots else 0
    pending := if !failed && collection.snapshots == 0 &&
        !policy.full && !policy.deferIndex then policy.prior else true
    acknowledged := !failed && policy.full && !policy.deferIndex
    indexAttempted := attempted
    failed := failed }

theorem phases_equal_projection (policy : Policy) (collection : Collection) :
    execute policy collection = projected policy collection := by
  rcases policy with ⟨full, prior, indexFailure, deferIndex⟩
  rcases collection with ⟨snapshots, fatal, sourceError⟩
  by_cases empty : snapshots = 0
  · subst snapshots
    cases full <;> cases prior <;> cases indexFailure <;> cases deferIndex <;>
      cases fatal <;> cases sourceError <;>
      decide
  · have nonempty : (snapshots == 0) = false := by simp [empty]
    cases full <;> cases prior <;> cases indexFailure <;> cases deferIndex <;>
      cases fatal <;> cases sourceError <;>
      simp [execute, restore, acknowledge, index, projected, nonempty, empty]

/-- Reusing a related collection result preserves every later policy observation. -/
theorem collection_substitution (policy : Policy) (left right : Collection)
    (same : left = right) : execute policy left = execute policy right := by
  cases same
  rfl

theorem fatal_ignores_source_error (policy : Policy) (snapshots : Nat)
    (sourceError : Bool) :
    execute policy ⟨snapshots, true, sourceError⟩ =
      execute policy ⟨snapshots, true, false⟩ := by
  rfl

/-- All policy fields remain available after collecting each full/kind input once. -/
def withPolicy (collection : Collection) (policies : List Policy) : List Outcome :=
  policies.map (fun policy => execute policy collection)

theorem every_policy_retained (collection : Collection) (policies : List Policy) :
    (withPolicy collection policies).length = policies.length := by
  simp [withPolicy]

/-- The wrapper can decide the restore write before its final pending-state read. -/
def restorePrevious (changed externalChanged full deferred : Bool) : Bool :=
  !(changed || externalChanged || full || deferred)

/-- A true result short-circuits the final pending-state read in the native wrapper. -/
def immediateProceed (changed externalChanged unconditional : Bool) : Bool :=
  changed || externalChanged || unconditional

/-- A successful fetch composes the two pure decisions with its actual pending state. -/
def finishFetch (previous : Pipeline.Pending) (changed externalChanged full deferred
    unconditional : Bool) : Pipeline.Pending × Bool :=
  let marked := Pipeline.require previous Pipeline.stages full
  let pending := if restorePrevious changed externalChanged full deferred then
    previous else marked
  (pending, immediateProceed changed externalChanged unconditional ||
    !pending.remaining.isEmpty)

theorem unchanged_fetch_restores_exactly (previous : Pipeline.Pending)
    (unconditional : Bool) :
    finishFetch previous false false false false unconditional =
      (previous, unconditional || !previous.remaining.isEmpty) := by
  simp [finishFetch, restorePrevious, immediateProceed]

theorem deferred_inputs_keep_required_work (previous : Pipeline.Pending)
    (full unconditional : Bool) :
    (finishFetch previous false false full true unconditional).1 =
      Pipeline.require previous Pipeline.stages full := by
  cases full <;> simp [finishFetch, restorePrevious]

/-- Absence of a completed state represents a real no-write boundary in Python. -/
def completedState (state : Pipeline.Pending) (stage : Pipeline.Stage) :
    Option Pipeline.Pending :=
  match state.remaining with
  | [] => none
  | first :: _ =>
    if first = stage then some (Pipeline.complete state stage) else none

theorem completion_matches_existing_state (state : Pipeline.Pending)
    (stage : Pipeline.Stage) :
    (completedState state stage).getD state = Pipeline.complete state stage := by
  rcases state with ⟨remaining, unconditional⟩
  cases remaining with
  | nil => rfl
  | cons first rest =>
    by_cases matching : first = stage
    · simp [completedState, Pipeline.complete, matching]
    · simp [completedState, Pipeline.complete, matching]

end PeriScribe.FetchComposition
