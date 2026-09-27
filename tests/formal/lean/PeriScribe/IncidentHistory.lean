import PeriScribe.Reconciliation
import PeriScribe.AreaHistory

namespace PeriScribe.IncidentHistory

/-- Fields have independent confirmation clocks; field zero denotes incident acreage. -/
structure Entry where
  time : Nat
  direct : Bool
  serial : Nat
  file : Nat
  report : Option Nat
  confirmed : Bool
  field : Nat
  value : Nat
  deriving DecidableEq, Repr

/-- Stable source ordering precedes field reconciliation at each observation time. -/
def before (first second : Entry) : Bool :=
  first.time < second.time || (first.time == second.time &&
    ((!first.direct && second.direct) || (first.direct == second.direct &&
      (first.serial < second.serial ||
        (first.serial == second.serial && first.file ≤ second.file)))))

def confirmation (entry : Entry) : Option Nat :=
  if entry.confirmed then entry.report else none

/-- Identical measurements keep the newest formal evidence, otherwise priority wins. -/
def winner (previous current : Entry) : Entry :=
  if previous.value = current.value then
    match confirmation previous, confirmation current with
    | some _, none => previous
    | some old, some new => if new < old then previous else current
    | _, _ => current
  else current

theorem winner_is_source (previous current : Entry) :
    winner previous current = previous ∨ winner previous current = current := by
  unfold winner
  split
  · cases confirmation previous with
    | none => simp
    | some old =>
      cases confirmation current with
      | none => simp
      | some new =>
        by_cases newer : new < old <;> simp [newer]
  · exact Or.inr rfl

/-- Each time/field bucket produces at most one supporting observation. -/
def select : List Entry → Option Entry
  | [] => none
  | entry :: rest => some (rest.foldl winner entry)

theorem winner_fold_preserves (predicate : Entry → Prop) (entries : List Entry)
    (initial : Entry) (prior : predicate initial)
    (observed : ∀ entry ∈ entries, predicate entry) :
    predicate (entries.foldl winner initial) := by
  induction entries generalizing initial with
  | nil => exact prior
  | cons entry rest induction =>
    apply induction _ ?_ (fun item member => observed item (by simp [member]))
    rcases winner_is_source initial entry with old | new
    · rw [old]; exact prior
    · rw [new]; exact observed entry (by simp)

theorem select_is_source (entries : List Entry) (entry : Entry)
    (selected : select entries = some entry) : entry ∈ entries := by
  cases entries with
  | nil => simp [select] at selected
  | cons first rest =>
    have supported := winner_fold_preserves (fun item => item ∈ first :: rest)
      rest first (by simp) (by simp_all)
    simp only [select, Option.some.injEq] at selected
    rwa [selected] at supported

/-- Sorting timestamps makes chronological output a construction guarantee. -/
def times (entries : List Entry) : List Nat :=
  (entries.map Entry.time).eraseDups.mergeSort

def fields (entries : List Entry) : List Nat :=
  (entries.map Entry.field).eraseDups.mergeSort

def simultaneous (entries : List Entry) (time : Nat) : List Entry :=
  (fields entries).filterMap fun field => select
    ((entries.mergeSort before).filter fun item =>
      item.time == time && item.field == field)

def merged (entries : List Entry) : List Entry :=
  (times entries).flatMap (simultaneous entries)

theorem simultaneous_is_source (entries : List Entry) (time : Nat) (entry : Entry)
    (member : entry ∈ simultaneous entries time) :
    entry ∈ entries ∧ entry.time = time := by
  rcases List.mem_filterMap.mp member with ⟨field, _, selected⟩
  have present := select_is_source _ entry selected
  have filtered := List.mem_filter.mp present
  constructor
  · exact List.mem_mergeSort.mp filtered.1
  · have dated : entry.time = time ∧ entry.field = field := by
      simpa using filtered.2
    exact dated.1

theorem merged_is_source (entries : List Entry) (entry : Entry)
    (member : entry ∈ merged entries) : entry ∈ entries := by
  rcases List.mem_flatMap.mp member with ⟨time, _, present⟩
  exact (simultaneous_is_source entries time entry present).1

abbrev Ledger := Nat → Option Entry

/-- Substituted values retain edit metadata; the ledger retains original support. -/
def protect (ledger : Ledger) (entry : Entry) : Entry :=
  match ledger entry.field, entry.report with
  | some prior, some reported =>
    if !entry.confirmed && reported ≤ prior.report.getD 0 &&
        !(entry.field == 0 && prior.value < entry.value)
    then { entry with value := prior.value } else entry
  | _, _ => entry

/-- Only a dated formal report can replace a field's confirmation ledger entry. -/
def remember (ledger : Ledger) (entry : Entry) : Ledger :=
  if entry.confirmed && entry.report.isSome then
    fun field => if field = entry.field then some entry else ledger field
  else ledger

/-- Sparse fields stay absent rather than borrowing unrelated observations. -/
def run (ledger : Ledger) : List Entry → List Entry
  | [] => []
  | entry :: rest =>
    let output := protect ledger entry
    output :: run (remember ledger output) rest

def reconcile (entries : List Entry) : List Entry :=
  run (fun _ => none) (merged entries)

def LedgerSupports (predicate : Nat → Nat → Prop) (ledger : Ledger) : Prop :=
  ∀ field entry, ledger field = some entry →
    entry.field = field ∧ predicate field entry.value

theorem protect_keeps_identity (ledger : Ledger) (entry : Entry) :
    (protect ledger entry).field = entry.field ∧
    (protect ledger entry).time = entry.time ∧
    (protect ledger entry).direct = entry.direct ∧
    (protect ledger entry).serial = entry.serial ∧
    (protect ledger entry).file = entry.file ∧
    (protect ledger entry).report = entry.report ∧
    (protect ledger entry).confirmed = entry.confirmed := by
  unfold protect
  split
  · split <;> simp
  · simp

theorem protection_only_uses_field_evidence (predicate : Nat → Nat → Prop)
    (ledger : Ledger) (entry : Entry) (prior : LedgerSupports predicate ledger)
    (observed : predicate entry.field entry.value) :
    predicate (protect ledger entry).field (protect ledger entry).value := by
  unfold protect
  split
  · rename_i previous reported known _
    split
    · exact (prior entry.field previous known).2
    · exact observed
  · exact observed

theorem remember_preserves_support (predicate : Nat → Nat → Prop)
    (ledger : Ledger) (entry : Entry) (prior : LedgerSupports predicate ledger)
    (observed : predicate entry.field entry.value) :
    LedgerSupports predicate (remember ledger entry) := by
  intro field item known
  unfold remember at known
  split at known
  · dsimp only at known
    split at known
    · rename_i same
      cases Option.some.inj known
      exact ⟨same.symm, by simpa [same] using observed⟩
    · exact prior field item known
  · exact prior field item known

theorem histories_keep_field_evidence (predicate : Nat → Nat → Prop)
    (ledger : Ledger) (entries : List Entry) (prior : LedgerSupports predicate ledger)
    (observed : ∀ entry ∈ entries, predicate entry.field entry.value) :
    ∀ entry ∈ run ledger entries, predicate entry.field entry.value := by
  induction entries generalizing ledger with
  | nil => simp [run]
  | cons entry rest induction =>
    have supported := protection_only_uses_field_evidence predicate ledger entry prior
      (observed entry (by simp))
    intro output present
    simp only [run, List.mem_cons] at present
    rcases present with current | later
    · simpa [current] using supported
    · exact induction _ (remember_preserves_support predicate ledger _ prior supported)
        (fun item member => observed item (by simp [member])) output later

theorem reconciliation_values_have_same_field_source (entries : List Entry)
    (output : Entry) (present : output ∈ reconcile entries) :
    ∃ input ∈ entries, input.field = output.field ∧ input.value = output.value := by
  apply histories_keep_field_evidence
    (fun field value => ∃ input ∈ entries, input.field = field ∧ input.value = value)
    _ _ ?_ ?_ output present
  · intro field entry impossible; contradiction
  · intro entry member
    exact ⟨entry, merged_is_source entries entry member, rfl, rfl⟩

theorem history_preserves_observation_fields (ledger : Ledger) (entries : List Entry) :
    (run ledger entries).map (fun entry => (entry.time, entry.field)) =
      entries.map (fun entry => (entry.time, entry.field)) := by
  induction entries generalizing ledger with
  | nil => rfl
  | cons entry rest induction =>
    simp only [run, List.map_cons, induction]
    rw [(protect_keeps_identity ledger entry).1,
      (protect_keeps_identity ledger entry).2.1]

theorem unconfirmed_cannot_change_ledger (ledger : Ledger) (entry : Entry)
    (unconfirmed : entry.confirmed = false) : remember ledger entry = ledger := by
  simp [remember, unconfirmed]

theorem missing_report_cannot_change_ledger (ledger : Ledger) (entry : Entry)
    (undated : entry.report = none) : remember ledger entry = ledger := by
  simp [remember, undated]

theorem fields_have_independent_ledgers (ledger : Ledger) (entry : Entry) (field : Nat)
    (different : field ≠ entry.field) : remember ledger entry field = ledger field := by
  unfold remember
  split <;> simp [different]

theorem stale_nonarea_cannot_undo_confirmation (ledger : Ledger) (entry prior : Entry)
    (known : ledger entry.field = some prior) (report : Nat)
    (dated : entry.report = some report) (stale : report ≤ prior.report.getD 0)
    (unconfirmed : entry.confirmed = false) (nonarea : entry.field ≠ 0) :
    (protect ledger entry).value = prior.value := by
  simp [protect, known, dated, stale, unconfirmed, nonarea]

theorem stale_area_cannot_decrease_confirmation (ledger : Ledger) (entry prior : Entry)
    (known : ledger entry.field = some prior) (report : Nat)
    (dated : entry.report = some report) (stale : report ≤ prior.report.getD 0)
    (unconfirmed : entry.confirmed = false) (area : entry.field = 0) :
    prior.value ≤ (protect ledger entry).value := by
  have knownArea : ledger 0 = some prior := by simpa [area] using known
  by_cases growth : prior.value < entry.value
  · simpa [protect, dated, unconfirmed, area, knownArea, growth]
      using Nat.le_of_lt growth
  · simp [protect, dated, stale, unconfirmed, area, knownArea, growth]

theorem merged_is_chronological (entries : List Entry) :
    (merged entries).Pairwise (fun first second => first.time ≤ second.time) := by
  apply List.pairwise_flatMap.mpr
  constructor
  · intro time _
    apply List.pairwise_of_forall_mem_list
    intro first firstMember second secondMember
    rw [(simultaneous_is_source entries time first firstMember).2,
      (simultaneous_is_source entries time second secondMember).2]
    exact Nat.le_refl time
  · have ordered : (times entries).Pairwise (fun first second => first ≤ second) := by
      unfold times
      apply List.Pairwise.imp (fun {_ _} relation => of_decide_eq_true relation)
      apply List.pairwise_mergeSort
      · intro first middle last one two
        exact decide_eq_true (Nat.le_trans
          (of_decide_eq_true one) (of_decide_eq_true two))
      · intro first second
        simp only [Bool.or_eq_true, decide_eq_true_eq]
        omega
    apply ordered.imp
    intro first second ordered left leftMember right rightMember
    rw [(simultaneous_is_source entries first left leftMember).2,
      (simultaneous_is_source entries second right rightMember).2]
    exact ordered

theorem reconcile_is_chronological (entries : List Entry) :
    (reconcile entries).Pairwise (fun first second => first.time ≤ second.time) := by
  have kept := history_preserves_observation_fields (fun _ => none) (merged entries)
  have equalTimes := congrArg (List.map Prod.fst) kept
  simp only [List.map_map, Function.comp_def] at equalTimes
  apply (List.pairwise_map (R := (· ≤ ·)) (f := Entry.time)).mp
  unfold reconcile
  rw [equalTimes]
  exact List.pairwise_map.mpr (merged_is_chronological entries)

/-- A retained value must already have been observed when it is carried forward. -/
def SupportedBy (sources : List Entry) (time field value : Nat) : Prop :=
  ∃ source ∈ sources, source.field = field ∧ source.value = value ∧ source.time ≤ time

theorem run_values_are_causal (sources entries : List Entry) (ledger : Ledger)
    (ordered : entries.Pairwise (fun first second => first.time ≤ second.time))
    (observed : ∀ entry ∈ entries, entry ∈ sources)
    (initial : ∀ entry ∈ entries,
      LedgerSupports (SupportedBy sources entry.time) ledger) :
    ∀ output ∈ run ledger entries,
      SupportedBy sources output.time output.field output.value := by
  induction entries generalizing ledger with
  | nil => simp [run]
  | cons entry rest induction =>
    have ordering := List.pairwise_cons.mp ordered
    have prior := initial entry (by simp)
    have supplied : SupportedBy sources entry.time entry.field entry.value :=
      ⟨entry, observed entry (by simp), rfl, rfl, Nat.le_refl _⟩
    have supported := protection_only_uses_field_evidence _ ledger entry prior supplied
    have known := remember_preserves_support _ ledger (protect ledger entry)
      prior supported
    intro output present
    simp only [run, List.mem_cons] at present
    rcases present with current | later
    · subst output
      rw [(protect_keeps_identity ledger entry).2.1]
      exact supported
    · apply induction _ ordering.2
        (fun item member => observed item (by simp [member])) ?_ output later
      intro next member field retained chosen
      have support := known field retained chosen
      constructor
      · exact support.1
      · obtain ⟨source, present, sameField, sameValue, dated⟩ := support.2
        exact ⟨source, present, sameField, sameValue,
          Nat.le_trans dated (ordering.1 next member)⟩

theorem reconciliation_values_have_earlier_support (entries : List Entry)
    (output : Entry) (present : output ∈ reconcile entries) :
    SupportedBy entries output.time output.field output.value := by
  apply run_values_are_causal entries (merged entries) (fun _ => none)
    (merged_is_chronological entries) (merged_is_source entries) ?_ output present
  intro entry member field prior impossible
  contradiction

/-- Omissions never erase a known measurement in the latest view. -/
def latest (entries : List Entry) (field : Nat) : Option Nat :=
  AreaHistory.last?
    ((entries.filter (fun entry => entry.field == field)).map Entry.value)

theorem latest_ignores_omitted_field
    (entries : List Entry) (entry : Entry) (field : Nat)
    (omitted : entry.field ≠ field) :
    latest (entries ++ [entry]) field = latest entries field := by
  simp [latest, omitted]

/-- Independent incident history takes precedence over all polygon-derived reports. -/
def authoritative (independent fallback : List Entry) : List Entry :=
  if independent.isEmpty then fallback else independent

theorem polygon_changes_cannot_erase_independent_reports
    (independent first second : List Entry) (present : independent ≠ []) :
    reconcile (authoritative independent first) =
      reconcile (authoritative independent second) := by
  simp [authoritative, List.isEmpty_iff, present]

end PeriScribe.IncidentHistory
