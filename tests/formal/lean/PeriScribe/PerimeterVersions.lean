import Std

namespace PeriScribe.PerimeterVersions

/-- Integer footprints are unit-height rectangles; GEOS is a conformance boundary. -/
structure Observation where
  identity : Nat
  time : Nat
  published : Nat
  serial : Nat
  object : Nat
  feed : Nat
  source : Nat
  category : Nat
  start : Nat
  width : Nat
  capture : Option Nat := none
  captureSameYear : Bool := true
  flight : Bool := false
  ancestors : List Nat := []
  deriving Repr

def lineage (observation : Observation) : List Nat :=
  observation.identity :: observation.ancestors

/-- A retained source reference represents both the winning and discarded evidence. -/
def inherit (winner loser : Observation) : Observation :=
  { winner with ancestors :=
    (winner.ancestors ++ loser.ancestors ++ [loser.identity]).eraseDups }

theorem inheritance_conserves_all_provenance (winner loser : Observation)
    (source : Nat) :
    source ∈ lineage (inherit winner loser) ↔
      source ∈ lineage winner ∨ source ∈ lineage loser := by
  simp [lineage, inherit, List.mem_eraseDups]
  simp only [or_assoc, or_comm, or_left_comm]

/-- A later publication alone cannot establish a fresh survey. -/
def newCapture (previous current : Observation) : Bool :=
  decide (previous.time < current.time) &&
    ((current.flight && decide (current.object ≠ previous.object)) ||
      match current.capture with
      | none => false
      | some capture => current.captureSameYear &&
          decide (previous.time < capture ∧ capture ≤ current.time))

theorem publication_alone_is_not_a_survey (previous current : Observation)
    (notFlight : current.flight = false) (noCapture : current.capture = none) :
    newCapture previous current = false := by simp [newCapture, notFlight, noCapture]

theorem fresh_capture_is_later (previous current : Observation)
    (fresh : newCapture previous current = true) : previous.time < current.time := by
  simp only [newCapture, Bool.and_eq_true, decide_eq_true_eq] at fresh
  exact fresh.1

def sameShape (first second : Observation) : Bool :=
  first.start == second.start && first.width == second.width

/-- Reversed output permits constant-time access to the retained preceding version. -/
def collapseStep (retained : List Observation) (current : Observation) :
    List Observation :=
  match retained with
  | [] => [current]
  | previous :: rest =>
    if sameShape previous current && !newCapture previous current then
      { inherit current previous with time := previous.time } :: rest
    else current :: retained

def collapse (observations : List Observation) : List Observation :=
  (observations.foldl collapseStep []).reverse

theorem republication_preserves_effective_time (previous current : Observation)
    (rest : List Observation) (same : sameShape previous current = true)
    (notFresh : newCapture previous current = false) :
    (collapseStep (previous :: rest) current).head?.map Observation.time =
      some previous.time := by simp [collapseStep, same, notFresh]

def covered (observations : List Observation) (source : Nat) : Prop :=
  ∃ observation ∈ observations, source ∈ lineage observation

theorem collapse_step_conserves_provenance (retained : List Observation)
    (current : Observation) (source : Nat) :
    covered (collapseStep retained current) source ↔
      covered retained source ∨ source ∈ lineage current := by
  cases retained with
  | nil => simp [collapseStep, covered]
  | cons previous rest =>
    simp only [collapseStep]
    split
    · simp only [covered, List.mem_cons, exists_eq_or_imp]
      change (source ∈ lineage (inherit current previous) ∨ _) ↔ _
      rw [inheritance_conserves_all_provenance]
      simp only [or_assoc, or_comm]
    · simp [covered]
      simp only [or_comm]

theorem collapse_fold_conserves_provenance (observations retained : List Observation)
    (source : Nat) :
    covered (observations.foldl collapseStep retained) source ↔
      covered retained source ∨ covered observations source := by
  induction observations generalizing retained with
  | nil => simp [covered]
  | cons current rest induction =>
    rw [List.foldl_cons, induction, collapse_step_conserves_provenance]
    simp only [covered, List.mem_cons, exists_eq_or_imp]
    simp only [or_assoc, or_comm, or_left_comm]

theorem complete_collapse_conserves_provenance (observations : List Observation)
    (source : Nat) :
    covered (collapse observations) source ↔ covered observations source := by
  simp only [collapse, covered, List.mem_reverse]
  change covered (observations.foldl collapseStep []) source ↔
    covered observations source
  rw [collapse_fold_conserves_provenance]
  simp [covered]

/-- Cross multiplication isolates rational overlap thresholds from floating point. -/
def overlap (first second : Observation) (percent : Nat) : Bool :=
  let intersection := min (first.start + first.width) (second.start + second.width) -
    max first.start second.start
  let union := first.width + second.width - intersection
  decide (0 < first.width ∧ 0 < second.width ∧ 0 < union ∧
    percent * union ≤ 100 * intersection)

def revisionPair (first second : Observation) : Bool :=
  decide (first.time ≤ second.time ∧ second.time ≤ first.time + 300) &&
    first.feed == second.feed && decide (0 < first.source) &&
    first.source == second.source &&
    decide (0 < first.category) && first.category == second.category &&
    overlap first second 99

def laterPublication (first second : Observation) : Bool :=
  decide (first.published < second.published ∨
    (first.published = second.published ∧ first.serial < second.serial) ∨
    (first.published = second.published ∧ first.serial = second.serial ∧
      first.object < second.object))

def revisionWinner (previous current : Observation) : Observation :=
  if laterPublication previous current then inherit current previous
  else inherit previous current

theorem revision_winner_conserves_provenance (previous current : Observation)
    (source : Nat) : source ∈ lineage (revisionWinner previous current) ↔
      source ∈ lineage previous ∨ source ∈ lineage current := by
  unfold revisionWinner
  split <;> rw [inheritance_conserves_all_provenance] <;> simp only [or_comm]

/-- Members are proof witnesses; only anchor and retained evidence affect decisions. -/
structure RevisionGroup where
  anchor : Observation
  retained : Observation
  members : List Observation
  deriving Repr

def bounded (group : RevisionGroup) : Prop :=
  ∀ observation ∈ group.members,
    group.anchor.time ≤ observation.time ∧ observation.time ≤ group.anchor.time + 300

def revisionStep (groups : List RevisionGroup) (current : Observation) :
    List RevisionGroup :=
  match groups with
  | [] => [⟨current, current, [current]⟩]
  | group :: rest =>
    if revisionPair group.anchor current && revisionPair group.retained current then
      { anchor := group.anchor, retained := revisionWinner group.retained current,
        members := current :: group.members } :: rest
    else ⟨current, current, [current]⟩ :: groups

def revisionGroups (observations : List Observation) : List RevisionGroup :=
  (observations.foldl revisionStep []).reverse

theorem eligible_revision_is_anchor_bounded (first second : Observation)
    (eligible : revisionPair first second = true) :
    first.time ≤ second.time ∧ second.time ≤ first.time + 300 := by
  simp only [revisionPair, Bool.and_eq_true, decide_eq_true_eq, beq_iff_eq] at eligible
  exact eligible.1.1.1.1.1.1

theorem revision_step_keeps_anchor_bound (groups : List RevisionGroup)
    (current : Observation) (valid : ∀ group ∈ groups, bounded group) :
    ∀ group ∈ revisionStep groups current, bounded group := by
  cases groups with
  | nil => simp [revisionStep, bounded]
  | cons previous rest =>
    simp only [revisionStep]
    split
    next accepted =>
      simp only [Bool.and_eq_true] at accepted
      intro group member
      rcases List.mem_cons.mp member with same | later
      · subst group
        intro observation present
        rcases List.mem_cons.mp present with same | old
        · subst observation
          exact eligible_revision_is_anchor_bounded _ _
            accepted.1
        · exact valid previous (by simp) observation old
      · exact valid group (by simp [later])
    next =>
      intro group member
      rcases List.mem_cons.mp member with same | old
      · subst group
        simp [bounded]
      · exact valid group old

theorem revision_fold_keeps_anchor_bound (observations : List Observation)
    (groups : List RevisionGroup) (valid : ∀ group ∈ groups, bounded group) :
    ∀ group ∈ observations.foldl revisionStep groups, bounded group := by
  induction observations generalizing groups with
  | nil => exact valid
  | cons current rest induction =>
    exact induction _ (revision_step_keeps_anchor_bound groups current valid)

theorem chained_edits_cannot_extend_revision_window (observations : List Observation) :
    ∀ group ∈ revisionGroups observations, bounded group := by
  intro group member
  exact revision_fold_keeps_anchor_bound observations [] (by simp) group
    (by simpa [revisionGroups] using member)

theorem revision_step_conserves_provenance (groups : List RevisionGroup)
    (current : Observation) (source : Nat) :
    covered ((revisionStep groups current).map RevisionGroup.retained) source ↔
      covered (groups.map RevisionGroup.retained) source ∨
      source ∈ lineage current := by
  cases groups with
  | nil => simp [revisionStep, covered]
  | cons previous rest =>
    simp only [revisionStep]
    split
    · simp only [List.map_cons, covered, List.mem_cons, exists_eq_or_imp]
      rw [revision_winner_conserves_provenance]
      simp only [or_assoc, or_comm]
    · simp [covered, or_comm]

theorem revision_fold_conserves_provenance (observations : List Observation)
    (groups : List RevisionGroup) (source : Nat) :
    covered ((observations.foldl revisionStep groups).map RevisionGroup.retained)
      source ↔
      covered (groups.map RevisionGroup.retained) source ∨
      covered observations source := by
  induction observations generalizing groups with
  | nil => simp [covered]
  | cons current rest induction =>
    rw [List.foldl_cons, induction, revision_step_conserves_provenance]
    simp [covered, or_assoc]

/-- Capture metadata is credible only within two days of its publication. -/
def credible (observation : Observation) : Option Nat :=
  observation.capture.filter (fun captured => observation.captureSameYear &&
    decide (captured ≤ observation.time ∧ observation.time ≤ captured + 172800))

def superseded (observation preferred : Observation) : Bool :=
  match credible observation with
  | none => false
  | some capture => decide (preferred.time ≤ observation.time ∧
      capture ≤ (credible preferred).getD preferred.time + 14400) &&
      overlap observation preferred 95

def contemporaneous (first second : Observation) : Bool :=
  decide (first.time ≤ second.time + 14400 ∧ second.time ≤ first.time + 14400)

def canReplace (observation preferred : Observation) : Bool :=
  contemporaneous observation preferred || superseded observation preferred

/-- The first qualified preferred observation retains a losing observation's lineage. -/
def absorb (observation : Observation) : List Observation → Option (List Observation)
  | [] => none
  | preferred :: rest =>
    if canReplace observation preferred then
      some (inherit preferred observation :: rest)
    else (absorb observation rest).map (preferred :: ·)

theorem supersession_requires_a_witness (observation : Observation)
    (preferred result : List Observation)
    (replaced : absorb observation preferred = some result) :
    ∃ witness ∈ preferred, canReplace observation witness = true := by
  induction preferred generalizing result with
  | nil => simp [absorb] at replaced
  | cons first rest induction =>
    simp only [absorb] at replaced
    split at replaced
    next eligible => exact ⟨first, by simp, eligible⟩
    next =>
      rcases Option.map_eq_some_iff.mp replaced with ⟨later, replaced, _⟩
      rcases induction later replaced with ⟨witness, present, valid⟩
      exact ⟨witness, by simp [present], valid⟩

theorem supersession_conserves_provenance (observation : Observation)
    (preferred result : List Observation)
    (replaced : absorb observation preferred = some result)
    (source : Nat) : covered result source ↔
      covered preferred source ∨ source ∈ lineage observation := by
  induction preferred generalizing result with
  | nil => simp [absorb] at replaced
  | cons first rest induction =>
    simp only [absorb] at replaced
    split at replaced
    · cases Option.some.inj replaced
      simp only [covered, List.mem_cons, exists_eq_or_imp]
      rw [inheritance_conserves_all_provenance]
      simp only [or_assoc, or_comm]
    · rcases Option.map_eq_some_iff.mp replaced with ⟨later, laterReplaced, same⟩
      cases same
      have remaining := induction later laterReplaced
      simp only [covered, List.mem_cons, exists_eq_or_imp] at *
      rw [remaining]
      simp only [or_assoc]

/-- Freshness uses the last actual survey even across many unchanged publications. -/
structure Survey where
  time : Nat
  area : Nat
  shape : Nat
  capture : Option Nat
  sameYear : Bool
  flight : Bool
  deriving Repr

def hasSurveyEvidence (previous : Option Nat) (current : Survey) : Bool :=
  current.flight || match current.capture with
  | none => false
  | some capture => current.sameYear && decide (capture ≤ current.time) &&
      (previous.map (fun time => decide (time < capture))).getD true

def surveyed (previous : Option Survey) (current : Survey)
    (difference : Nat → Nat → Nat) : Bool :=
  match previous with
  | none => true
  | some old => hasSurveyEvidence (some old.time) current ||
      decide (1 ≤ difference old.shape current.shape ∧
        old.area ≤ 100 * difference old.shape current.shape)

def surveyStep (previous : Option Survey) (current : Survey)
    (difference : Nat → Nat → Nat) : Option Survey :=
  if surveyed previous current difference then some current else previous

def lastSurvey (observations : List Survey) (previous : Option Survey)
    (difference : Nat → Nat → Nat) : Option Survey :=
  observations.foldl (fun old current => surveyStep old current difference) previous

theorem insignificant_republication_does_not_move_survey (previous current : Survey)
    (difference : Nat → Nat → Nat)
    (notExplicit : hasSurveyEvidence (some previous.time) current = false)
    (insufficient : difference previous.shape current.shape = 0) :
    surveyStep (some previous) current difference = some previous := by
  simp [surveyStep, surveyed, notExplicit, insufficient]

theorem publication_without_evidence_is_not_a_survey (previous : Option Nat)
    (current : Survey) (notFlight : current.flight = false)
    (notCaptured : current.capture = none) :
    hasSurveyEvidence previous current = false := by
  simp [hasSurveyEvidence, notFlight, notCaptured]

theorem capture_evidence_is_not_from_the_future (previous : Option Nat)
    (current : Survey) (notFlight : current.flight = false)
    (evidence : hasSurveyEvidence previous current = true) :
    ∃ capture, current.capture = some capture ∧ capture ≤ current.time := by
  cases captured : current.capture with
  | none => simp [hasSurveyEvidence, notFlight, captured] at evidence
  | some capture =>
    simp only [hasSurveyEvidence, notFlight, Bool.false_or, captured,
      Bool.and_eq_true, decide_eq_true_eq] at evidence
    exact ⟨capture, rfl, evidence.1.2⟩

theorem ignored_publications_preserve_last_actual_survey (observations : List Survey)
    (previous : Survey) (difference : Nat → Nat → Nat)
    (unchanged : ∀ current ∈ observations,
      surveyed (some previous) current difference = false) :
    lastSurvey observations (some previous) difference = some previous := by
  induction observations with
  | nil => rfl
  | cons current rest induction =>
    simp only [lastSurvey, List.foldl_cons, surveyStep, unchanged current (by simp),
      Bool.false_eq_true, ite_false]
    exact induction (fun item member => unchanged item (by simp [member]))

end PeriScribe.PerimeterVersions
