namespace PeriScribe.LogSeeking

/-- Complete record lengths include their newline; the unfinished tail is separate. -/
structure Record where
  bytes : Nat
  timestamp : Option Nat
  included : Bool := true
  serial : Nat := 0
  deriving DecidableEq, Repr

def old (cutoff : Nat) (record : Record) : Bool :=
  record.timestamp.any (· < cutoff)

def size (records : List Record) : Nat := (records.map Record.bytes).sum

/-- The reference boundary is immediately after the final complete older timestamp. -/
def boundary (cutoff : Nat) : List Record → Nat
  | [] => 0
  | record :: rest =>
    let later := boundary cutoff rest
    if later > 0 then record.bytes + later
    else if old cutoff record then record.bytes else 0

def ordered (first second : Record) : Prop :=
  ∀ firstTime secondTime, first.timestamp = some firstTime →
    second.timestamp = some secondTime → firstTime ≤ secondTime

def chronological (records : List Record) : Prop := records.Pairwise ordered

theorem size_append (first second : List Record) :
    size (first ++ second) = size first + size second := by
  simp [size, List.sum_append]

theorem boundary_bounded (cutoff : Nat) (records : List Record) :
    boundary cutoff records ≤ size records := by
  induction records with
  | nil => simp [boundary, size]
  | cons record rest induction =>
    simp only [boundary, size, List.map_cons, List.sum_cons]
    split
    · simpa [size] using Nat.add_le_add_left induction record.bytes
    · split <;> simp_all [size] <;> omega

theorem no_old_boundary_zero (cutoff : Nat) (records : List Record)
    (noneOld : ∀ record ∈ records, old cutoff record = false) :
    boundary cutoff records = 0 := by
  induction records with
  | nil => rfl
  | cons record rest induction =>
    have first := noneOld record (by simp)
    have later := induction (by
      intro item member
      exact noneOld item (by simp [member]))
    simp [boundary, first, later]

theorem append_without_old_preserves_boundary (cutoff : Nat)
    (first second : List Record)
    (noneOld : ∀ record ∈ second, old cutoff record = false) :
    boundary cutoff (first ++ second) = boundary cutoff first := by
  induction first with
  | nil => simpa [boundary] using no_old_boundary_zero cutoff second noneOld
  | cons record rest induction => simp [boundary, induction]

theorem later_old_moves_boundary (cutoff : Nat) (first second : List Record)
    (positive : 0 < boundary cutoff second) :
    boundary cutoff (first ++ second) = size first + boundary cutoff second := by
  induction first with
  | nil => simp [size]
  | cons record rest induction =>
    have moved : 0 < boundary cutoff (rest ++ second) := by rw [induction]; omega
    simp only [List.cons_append, boundary]
    rw [ite_eq_left moved, induction]
    simp [size, Nat.add_assoc]

theorem exact_last_old_boundary (cutoff : Nat) (first rest : List Record)
    (record : Record) (positive : 0 < record.bytes)
    (older : old cutoff record = true)
    (last : ∀ later ∈ rest, old cutoff later = false) :
    boundary cutoff (first ++ record :: rest) = size first + record.bytes := by
  have suffix : boundary cutoff (record :: rest) = record.bytes := by
    simp [boundary, no_old_boundary_zero cutoff rest last, older]
  rw [later_old_moves_boundary cutoff first (record :: rest) (by simpa [suffix])]
  rw [suffix]

theorem suffix_without_old_is_not_skipped (cutoff : Nat) (first rest : List Record)
    (noneOld : ∀ record ∈ rest, old cutoff record = false) :
    boundary cutoff (first ++ rest) ≤ size first := by
  rw [append_without_old_preserves_boundary cutoff first rest noneOld]
  exact boundary_bounded cutoff first

theorem chronological_suffix_has_no_old (cutoff time : Nat) (record : Record)
    (rest : List Record) (sorted : chronological (record :: rest))
    (dated : record.timestamp = some time) (eligible : cutoff ≤ time) :
    ∀ later ∈ rest, old cutoff later = false := by
  intro later member
  have relation : ordered record later := (List.pairwise_cons.mp sorted).1 later member
  cases found : later.timestamp with
  | none => simp [old, found]
  | some laterTime =>
    have increasing := relation time laterTime dated found
    simp [old, found]
    omega

theorem eligible_record_is_not_skipped (cutoff time : Nat)
    (first rest : List Record) (record : Record)
    (sorted : chronological (first ++ record :: rest))
    (dated : record.timestamp = some time) (eligible : cutoff ≤ time) :
    boundary cutoff (first ++ record :: rest) ≤ size first := by
  have suffixSorted : chronological (record :: rest) :=
    (List.pairwise_append.mp sorted).2.1
  apply suffix_without_old_is_not_skipped
  intro item member
  simp only [List.mem_cons] at member
  rcases member with same | member
  · subst item
    simp [old, dated, Nat.not_lt.mpr eligible]
  · exact chronological_suffix_has_no_old cutoff time record rest suffixSorted
      dated eligible item member

theorem undated_after_last_old_is_not_skipped (cutoff : Nat)
    (first rest : List Record) (record : Record) (undated : record.timestamp = none)
    (later : ∀ item ∈ rest, old cutoff item = false) :
    boundary cutoff (first ++ record :: rest) ≤ size first := by
  apply suffix_without_old_is_not_skipped
  intro item member
  simp only [List.mem_cons] at member
  rcases member with same | member
  · subst item; simp [old, undated]
  · exact later item member

/-- An incomplete final record contributes bytes to the file, not a usable timestamp. -/
def seek (cutoff : Nat) (records : List Record) (_unfinishedBytes : Nat) : Nat :=
  boundary cutoff records

theorem unfinished_tail_preserves_boundary (cutoff : Nat) (records : List Record)
    (firstTail secondTail : Nat) :
    seek cutoff records firstTail = seek cutoff records secondTail := rfl

theorem seek_stays_in_complete_prefix (cutoff : Nat) (records : List Record)
    (unfinishedBytes : Nat) : seek cutoff records unfinishedBytes ≤ size records :=
  boundary_bounded cutoff records

def tooNew (upperBound : Option Nat) (record : Record) : Bool :=
  match upperBound, record.timestamp with
  | some upper, some time => upper < time
  | _, _ => false

/-- The upper bound applies after the inclusion filter, matching diagnostic scans. -/
def window (since : Nat) (upperBound : Option Nat) : List Record → List Record
  | [] => []
  | record :: rest =>
    if !record.included then window since upperBound rest
    else if tooNew upperBound record then []
    else if old since record then window since upperBound rest
    else record :: window since upperBound rest

theorem window_is_subsequence (since : Nat) (upperBound : Option Nat)
    (records : List Record) : (window since upperBound records).Sublist records := by
  induction records with
  | nil => simp [window]
  | cons record rest induction =>
    simp only [window]
    split
    · exact induction.cons _
    · split
      · exact List.nil_sublist _
      · split
        · exact induction.cons _
        · exact induction.cons_cons _

theorem window_contains_only_included_recent (since : Nat) (upperBound : Option Nat)
    (records : List Record) :
    ∀ record ∈ window since upperBound records,
      record.included = true ∧ old since record = false ∧
        tooNew upperBound record = false := by
  induction records with
  | nil => simp [window]
  | cons first rest induction =>
    simp only [window]
    split
    · exact induction
    · split
      · simp
      · split
        · exact induction
        · intro record member
          simp only [List.mem_cons] at member
          rcases member with same | member
          · subst record; simp_all
          · exact induction record member

def dropBytes (offset : Nat) : List Record → List Record
  | [] => []
  | record :: rest =>
    if offset = 0 then record :: rest else dropBytes (offset - record.bytes) rest

theorem drop_bytes_preserves_complete_suffix (first rest : List Record)
    (positive : ∀ record ∈ first, 0 < record.bytes) :
    dropBytes (size first) (first ++ rest) = rest := by
  induction first with
  | nil => cases rest <;> simp [size, dropBytes]
  | cons record first induction =>
    have positiveHead := positive record (by simp)
    have positiveTail : ∀ item ∈ first, 0 < item.bytes := by
      intro item member; exact positive item (by simp [member])
    have nonzero : record.bytes + size first ≠ 0 := by omega
    simp only [size, List.map_cons, List.sum_cons, List.cons_append]
    change dropBytes (record.bytes + size first) (record :: (first ++ rest)) = rest
    rw [dropBytes, ite_eq_right nonzero, Nat.add_sub_cancel_left]
    exact induction positiveTail

/-- Binary search uses byte offsets; an old probe jumps to its complete record end. -/
def binarySearch (probe : Nat → Option Nat) : Nat → Nat → Nat → Nat
  | 0, lower, _ => lower
  | fuel + 1, lower, upper =>
    if lower < upper then
      let middle := (lower + upper) / 2
      match probe middle with
      | some next => binarySearch probe fuel next upper
      | none => binarySearch probe fuel lower middle
    else lower

/-- The final old record starts at `lastStart` and ends at `lastEnd`. -/
def ProbeContract (probe : Nat → Option Nat) (lastStart lastEnd : Nat) : Prop :=
  (∀ offset, probe offset = none ↔ lastStart < offset) ∧
  (∀ offset next, probe offset = some next →
    offset < next ∧ next ≤ lastEnd ∧ (next ≤ lastStart ∨ next = lastEnd))

theorem binary_search_finds_last_complete_old_end
    (probe : Nat → Option Nat) (lastStart lastEnd fuel lower upper : Nat)
    (contract : ProbeContract probe lastStart lastEnd)
    (upperPastStart : lastStart < upper)
    (lowerCandidate : lower ≤ lastStart ∨ lower = lastEnd)
    (lowerBounded : lower ≤ lastEnd)
    (enough : upper - lower < fuel) :
    binarySearch probe fuel lower upper = lastEnd := by
  induction fuel generalizing lower upper with
  | zero => omega
  | succ fuel induction =>
    simp only [binarySearch]
    split
    next active =>
      have middleLow : lower ≤ (lower + upper) / 2 := by omega
      have middleHigh : (lower + upper) / 2 < upper := by omega
      cases found : probe ((lower + upper) / 2) with
      | none =>
        have beyond := (contract.1 _).mp found
        exact induction lower ((lower + upper) / 2) beyond lowerCandidate lowerBounded
          (by omega)
      | some next =>
        obtain ⟨progress, bounded, candidate⟩ := contract.2 _ _ found
        exact induction next upper upperPastStart candidate bounded (by omega)
    next finished =>
      rcases lowerCandidate with before | final
      · omega
      · exact final

theorem binary_search_without_old_records (probe : Nat → Option Nat)
    (noneOld : ∀ offset, probe offset = none) (fuel lower upper : Nat) :
    binarySearch probe fuel lower upper = lower := by
  induction fuel generalizing lower upper with
  | zero => rfl
  | succ fuel induction =>
    simp only [binarySearch]
    split
    · simp only [noneOld]; exact induction _ _
    · rfl

/-- Complete old records occupy disjoint byte intervals; undated records leave gaps. -/
def intervalProbe (intervals : List (Nat × Nat)) (offset : Nat) : Option Nat :=
  (intervals.find? (fun entry => offset ≤ entry.1)).map Prod.snd

theorem interval_probe_contract (first : List (Nat × Nat)) (last : Nat × Nat)
    (positive : ∀ entry ∈ first ++ [last], entry.1 < entry.2)
    (beforeLast : ∀ entry ∈ first, entry.2 ≤ last.1) :
    ProbeContract (intervalProbe (first ++ [last])) last.1 last.2 := by
  have lastPositive := positive last (by simp)
  constructor
  · intro offset
    simp only [intervalProbe, Option.map_eq_none_iff, List.find?_eq_none]
    constructor
    · intro absent
      have missing := absent last (by simp)
      simpa using missing
    · intro afterLast entry member
      have extent := positive entry member
      simp only [List.mem_append, List.mem_singleton] at member
      rcases member with earlier | same
      · have before := beforeLast entry earlier
        simp; omega
      · subst entry; simp_all
  · intro offset next found
    simp only [intervalProbe, Option.map_eq_some_iff] at found
    obtain ⟨entry, selected, result⟩ := found
    have member := List.mem_of_find?_eq_some selected
    have starts : offset ≤ entry.1 := by simpa using List.find?_some selected
    have extent := positive entry member
    simp only [List.mem_append, List.mem_singleton] at member
    rcases member with earlier | same
    · have before := beforeLast entry earlier
      constructor
      · omega
      · constructor
        · omega
        · left; omega
    · subst entry
      simp_all
      omega

theorem binary_search_complete_record_intervals (first : List (Nat × Nat))
    (last : Nat × Nat) (fileBytes : Nat)
    (positive : ∀ entry ∈ first ++ [last], entry.1 < entry.2)
    (beforeLast : ∀ entry ∈ first, entry.2 ≤ last.1)
    (withinFile : last.2 ≤ fileBytes) :
    binarySearch (intervalProbe (first ++ [last]))
      (fileBytes + 1) 0 fileBytes = last.2 := by
  have lastPositive := positive last (by simp)
  exact binary_search_finds_last_complete_old_end _ _ _ _ _ _
    (interval_probe_contract first last positive beforeLast)
    (by omega) (Or.inl (by omega)) (by omega) (by omega)

def oldIntervals (cutoff offset : Nat) : List Record → List (Nat × Nat)
  | [] => []
  | record :: rest =>
    let later := oldIntervals cutoff (offset + record.bytes) rest
    if old cutoff record then (offset, offset + record.bytes) :: later else later

theorem old_intervals_are_complete_and_bounded (cutoff offset : Nat)
    (records : List Record) (positive : ∀ record ∈ records, 0 < record.bytes) :
    ∀ entry ∈ oldIntervals cutoff offset records,
      offset ≤ entry.1 ∧ entry.1 < entry.2 ∧ entry.2 ≤ offset + size records := by
  induction records generalizing offset with
  | nil => simp [oldIntervals]
  | cons record rest induction =>
    have headPositive := positive record (by simp)
    have tailPositive : ∀ item ∈ rest, 0 < item.bytes := by
      intro item member; exact positive item (by simp [member])
    intro entry member
    simp only [oldIntervals] at member
    split at member
    · simp only [List.mem_cons] at member
      rcases member with same | member
      · subst entry; simp [size]; omega
      · obtain ⟨start, width, bound⟩ := induction (offset + record.bytes)
          tailPositive entry member
        simp only [size, List.map_cons, List.sum_cons]
        simp only [size] at bound
        omega
    · obtain ⟨start, width, bound⟩ := induction (offset + record.bytes)
        tailPositive entry member
      simp only [size, List.map_cons, List.sum_cons]
      simp only [size] at bound
      omega

theorem old_intervals_are_disjoint (cutoff offset : Nat) (records : List Record)
    (positive : ∀ record ∈ records, 0 < record.bytes) :
    (oldIntervals cutoff offset records).Pairwise (fun first second =>
      first.2 ≤ second.1) := by
  induction records generalizing offset with
  | nil => simp [oldIntervals]
  | cons record rest induction =>
    have tailPositive : ∀ item ∈ rest, 0 < item.bytes := by
      intro item member; exact positive item (by simp [member])
    simp only [oldIntervals]
    split
    · apply List.pairwise_cons.mpr
      constructor
      · intro entry member
        exact (old_intervals_are_complete_and_bounded cutoff (offset + record.bytes)
          rest tailPositive entry member).1
      · exact induction _ tailPositive
    · exact induction _ tailPositive

theorem generated_intervals_satisfy_binary_contract (cutoff : Nat)
    (records : List Record) (first : List (Nat × Nat)) (last : Nat × Nat)
    (positive : ∀ record ∈ records, 0 < record.bytes)
    (lastOld : oldIntervals cutoff 0 records = first ++ [last]) :
    ProbeContract (intervalProbe (oldIntervals cutoff 0 records)) last.1 last.2 := by
  rw [lastOld]
  apply interval_probe_contract
  · intro entry member
    exact (old_intervals_are_complete_and_bounded cutoff 0 records positive entry
      (by simpa [lastOld] using member)).2.1
  · have ordered := old_intervals_are_disjoint cutoff 0 records positive
    rw [lastOld] at ordered
    have cross := (List.pairwise_append.mp ordered).2.2
    intro entry member
    exact cross entry member last (by simp)

theorem binary_search_generated_complete_records (cutoff : Nat)
    (records : List Record) (first : List (Nat × Nat)) (last : Nat × Nat)
    (unfinishedBytes : Nat) (positive : ∀ record ∈ records, 0 < record.bytes)
    (lastOld : oldIntervals cutoff 0 records = first ++ [last]) :
    binarySearch (intervalProbe (oldIntervals cutoff 0 records))
      (size records + unfinishedBytes + 1) 0 (size records + unfinishedBytes) =
        last.2 := by
  have bounds := old_intervals_are_complete_and_bounded cutoff 0 records positive last
    (by simp [lastOld])
  apply binary_search_finds_last_complete_old_end
  · exact generated_intervals_satisfy_binary_contract cutoff records first last
      positive lastOld
  · omega
  · left; omega
  · omega
  · omega

/-- The byte probe stops at the first complete dated record at or after its offset. -/
def timestampProbe (cutoff offset query : Nat) : List Record → Option Nat
  | [] => none
  | record :: rest =>
    if query ≤ offset ∧ record.timestamp.isSome then
      if old cutoff record then some (offset + record.bytes) else none
    else timestampProbe cutoff (offset + record.bytes) query rest

theorem no_old_intervals (cutoff offset : Nat) (records : List Record)
    (noneOld : ∀ record ∈ records, old cutoff record = false) :
    oldIntervals cutoff offset records = [] := by
  induction records generalizing offset with
  | nil => rfl
  | cons record rest induction =>
    have first := noneOld record (by simp)
    have later := induction (offset + record.bytes) (by
      intro item member
      exact noneOld item (by simp [member]))
    simp [oldIntervals, first, later]

theorem chronological_timestamp_probe_matches_intervals (cutoff offset query : Nat)
    (records : List Record) (sorted : chronological records) :
    timestampProbe cutoff offset query records =
      intervalProbe (oldIntervals cutoff offset records) query := by
  induction records generalizing offset with
  | nil => simp [timestampProbe, oldIntervals, intervalProbe]
  | cons record rest induction =>
    have tailSorted := (List.pairwise_cons.mp sorted).2
    cases dated : record.timestamp with
    | none =>
      simp [timestampProbe, oldIntervals, old, dated, induction _ tailSorted]
    | some time =>
      by_cases older : time < cutoff
      · by_cases starts : query ≤ offset
        · simp [timestampProbe, oldIntervals, old, dated, older, starts,
            intervalProbe]
        · simp [timestampProbe, oldIntervals, old, dated, older, starts,
            intervalProbe] at *
          exact induction _ tailSorted
      · have noneOld := chronological_suffix_has_no_old cutoff time record rest
          sorted dated (by omega)
        have empty := no_old_intervals cutoff (offset + record.bytes) rest noneOld
        by_cases starts : query ≤ offset
        · simp [timestampProbe, oldIntervals, old, dated, older, starts, empty,
            intervalProbe]
        · simp [timestampProbe, oldIntervals, old, dated, older, starts,
            induction _ tailSorted]

theorem old_intervals_append (cutoff offset : Nat) (first second : List Record) :
    oldIntervals cutoff offset (first ++ second) =
      oldIntervals cutoff offset first ++
        oldIntervals cutoff (offset + size first) second := by
  induction first generalizing offset with
  | nil => simp [oldIntervals, size]
  | cons record rest induction =>
    simp only [List.cons_append, oldIntervals]
    split <;> simp [induction, size, Nat.add_assoc]

theorem binary_search_matches_last_old_boundary (cutoff : Nat)
    (first rest : List Record) (record : Record) (unfinishedBytes : Nat)
    (positive : ∀ item ∈ first ++ record :: rest, 0 < item.bytes)
    (older : old cutoff record = true)
    (noneOld : ∀ item ∈ rest, old cutoff item = false) :
    binarySearch (intervalProbe (oldIntervals cutoff 0 (first ++ record :: rest)))
      (size (first ++ record :: rest) + unfinishedBytes + 1)
      0 (size (first ++ record :: rest) + unfinishedBytes) =
        boundary cutoff (first ++ record :: rest) := by
  have intervals : oldIntervals cutoff 0 (first ++ record :: rest) =
      oldIntervals cutoff 0 first ++ [(size first, size first + record.bytes)] := by
    rw [old_intervals_append]
    simp [oldIntervals, older, no_old_intervals cutoff _ rest noneOld]
  rw [binary_search_generated_complete_records cutoff (first ++ record :: rest)
    _ _ unfinishedBytes positive intervals]
  exact (exact_last_old_boundary cutoff first rest record
    (positive record (by simp)) older noneOld).symm

theorem last_old_decomposition (cutoff : Nat) (records : List Record) :
    (∀ record ∈ records, old cutoff record = false) ∨
      ∃ first record rest, records = first ++ record :: rest ∧
        old cutoff record = true ∧ (∀ item ∈ rest, old cutoff item = false) := by
  induction records with
  | nil => left; simp
  | cons record rest induction =>
    rcases induction with noneOld | ⟨first, item, later, split, older, noneOld⟩
    · cases found : old cutoff record with
      | false => left; simp_all
      | true => right; exact ⟨[], record, rest, rfl, found, noneOld⟩
    · right
      exact ⟨record :: first, item, later, by simp [split], older, noneOld⟩

theorem binary_search_matches_reference (cutoff : Nat) (records : List Record)
    (unfinishedBytes : Nat) (positive : ∀ record ∈ records, 0 < record.bytes) :
    binarySearch (intervalProbe (oldIntervals cutoff 0 records))
      (size records + unfinishedBytes + 1) 0 (size records + unfinishedBytes) =
        seek cutoff records unfinishedBytes := by
  rcases last_old_decomposition cutoff records with noneOld |
    ⟨first, record, rest, split, older, noneOld⟩
  · simp only [no_old_intervals cutoff 0 records noneOld]
    rw [binary_search_without_old_records _ (by intro offset; rfl)]
    exact (no_old_boundary_zero cutoff records noneOld).symm
  · subst records
    exact binary_search_matches_last_old_boundary cutoff first rest record
      unfinishedBytes positive older noneOld

theorem chronological_byte_search_matches_reference (cutoff : Nat)
    (records : List Record) (unfinishedBytes : Nat)
    (positive : ∀ record ∈ records, 0 < record.bytes)
    (sorted : chronological records) :
    binarySearch (fun query => timestampProbe cutoff 0 query records)
      (size records + unfinishedBytes + 1) 0 (size records + unfinishedBytes) =
        seek cutoff records unfinishedBytes := by
  have probes : (fun query => timestampProbe cutoff 0 query records) =
      intervalProbe (oldIntervals cutoff 0 records) := by
    funext query
    exact chronological_timestamp_probe_matches_intervals cutoff 0 query records
      sorted
  rw [probes]
  exact binary_search_matches_reference cutoff records unfinishedBytes positive

/-- A dated occurrence at or beyond the lower bound stops prefix retirement. -/
def recent (cutoff : Nat) (record : Record) : Bool :=
  record.timestamp.any (cutoff ≤ ·)

/-- Retire only older records preceding the first eligible dated occurrence. -/
def safeBoundary (cutoff : Nat) : List Record → Nat
  | [] => 0
  | record :: rest =>
    if recent cutoff record then 0
    else
      let later := safeBoundary cutoff rest
      if later > 0 then record.bytes + later
      else if old cutoff record then record.bytes else 0

theorem safe_boundary_is_complete_prefix (cutoff : Nat) (records : List Record) :
    ∃ first rest, records = first ++ rest ∧ safeBoundary cutoff records = size first ∧
      (∀ record ∈ first, recent cutoff record = false) := by
  induction records with
  | nil => exact ⟨[], [], rfl, rfl, by simp⟩
  | cons record records induction =>
    by_cases eligible : recent cutoff record = true
    · exact ⟨[], record :: records, rfl, by simp [safeBoundary, eligible, size], by simp⟩
    · have ineligible : recent cutoff record = false := by simpa using eligible
      by_cases later : 0 < safeBoundary cutoff records
      · obtain ⟨first, rest, split, offset, noneRecent⟩ := induction
        refine ⟨record :: first, rest, by simp [split], ?_, ?_⟩
        · rw [safeBoundary, ite_eq_right eligible, ite_eq_left later, offset]
          simp [size]
        · intro item member
          simp only [List.mem_cons] at member
          rcases member with same | member
          · simpa [same] using ineligible
          · exact noneRecent item member
      · by_cases older : old cutoff record = true
        · refine ⟨[record], records, rfl, ?_, ?_⟩
          · simp [safeBoundary, ineligible, later, older, size]
          · simpa using ineligible
        · exact ⟨[], record :: records, rfl,
            by simp [safeBoundary, ineligible, later, older, size], by simp⟩

theorem safe_boundary_bounded (cutoff : Nat) (records : List Record) :
    safeBoundary cutoff records ≤ size records := by
  obtain ⟨first, rest, split, offset, _⟩ := safe_boundary_is_complete_prefix cutoff records
  rw [offset, split, size_append]
  omega

def safeSeek (cutoff : Nat) (records : List Record) (_unfinishedBytes : Nat) : Nat :=
  safeBoundary cutoff records

theorem safe_seek_ignores_incomplete_tail (cutoff : Nat) (records : List Record)
    (firstTail secondTail : Nat) :
    safeSeek cutoff records firstTail = safeSeek cutoff records secondTail := rfl

theorem safe_boundary_preserves_every_eligible_occurrence (cutoff time : Nat)
    (first rest : List Record) (record : Record)
    (dated : record.timestamp = some time) (eligible : cutoff ≤ time) :
    safeBoundary cutoff (first ++ record :: rest) ≤ size first := by
  induction first with
  | nil => simp [safeBoundary, recent, dated, eligible, size]
  | cons item first induction =>
    simp only [List.cons_append, safeBoundary]
    split
    · simp [size]
    · split
      · simpa [size] using Nat.add_le_add_left induction item.bytes
      · split <;> simp [size] <;> omega

theorem safe_boundary_equals_ordered_reference (cutoff : Nat) (records : List Record)
    (sorted : chronological records) : safeBoundary cutoff records = boundary cutoff records := by
  induction records with
  | nil => rfl
  | cons record records induction =>
    have tailSorted := (List.pairwise_cons.mp sorted).2
    cases dated : record.timestamp with
    | none => simp [safeBoundary, boundary, recent, dated, induction tailSorted]
    | some time =>
      by_cases eligible : cutoff ≤ time
      · have noneOld := chronological_suffix_has_no_old cutoff time record records
          sorted dated eligible
        simp [safeBoundary, boundary, recent, old, dated, eligible,
          no_old_boundary_zero cutoff records noneOld, Nat.not_lt.mpr eligible]
      · simp [safeBoundary, boundary, recent, dated, eligible, induction tailSorted]

/-- An implementation scan carries its current byte position and last retired end. -/
def scanBoundary (cutoff offset saved : Nat) : List Record → Nat
  | [] => saved
  | record :: rest =>
    if recent cutoff record then saved
    else scanBoundary cutoff (offset + record.bytes)
      (if old cutoff record then offset + record.bytes else saved) rest

theorem scan_boundary_matches_reference (cutoff offset saved : Nat)
    (records : List Record) (positive : ∀ record ∈ records, 0 < record.bytes) :
    scanBoundary cutoff offset saved records =
      if safeBoundary cutoff records > 0 then offset + safeBoundary cutoff records
      else saved := by
  induction records generalizing offset saved with
  | nil => simp [scanBoundary, safeBoundary]
  | cons record records induction =>
    have headPositive := positive record (by simp)
    have tailPositive : ∀ item ∈ records, 0 < item.bytes := by
      intro item member; exact positive item (by simp [member])
    simp only [scanBoundary, safeBoundary]
    split
    · simp
    · rw [induction _ _ tailPositive]
      split
      · have totalPositive : 0 < record.bytes + safeBoundary cutoff records := by omega
        simp_all [Nat.add_assoc]
      · split <;> simp_all

theorem scan_starts_at_safe_boundary (cutoff : Nat) (records : List Record)
    (positive : ∀ record ∈ records, 0 < record.bytes) :
    scanBoundary cutoff 0 0 records = safeBoundary cutoff records := by
  rw [scan_boundary_matches_reference cutoff 0 0 records positive]
  split <;> simp_all <;> omega

/-- Every occurrence is tested independently; rollback never authorizes early EOF. -/
def admitted (since : Nat) (upperBound : Option Nat) (record : Record) : Bool :=
  record.included && !old since record && !tooNew upperBound record

def safeWindow (since : Nat) (upperBound : Option Nat) (records : List Record) : List Record :=
  records.filter (admitted since upperBound)

theorem safe_window_preserves_order_and_multiplicity (since : Nat)
    (upperBound : Option Nat) (records : List Record) :
    (safeWindow since upperBound records).Sublist records := List.filter_sublist

theorem safe_window_membership (since : Nat) (upperBound : Option Nat)
    (records : List Record) (record : Record) :
    record ∈ safeWindow since upperBound records ↔
      record ∈ records ∧ admitted since upperBound record = true := by
  simp [safeWindow]

theorem safe_window_distributes_over_appends (since : Nat) (upperBound : Option Nat)
    (first second : List Record) :
    safeWindow since upperBound (first ++ second) =
      safeWindow since upperBound first ++ safeWindow since upperBound second := by
  simp [safeWindow]

theorem safe_window_ignores_later_clock_direction (since : Nat)
    (upperBound : Option Nat) (first rest : List Record) (record : Record)
    (eligible : admitted since upperBound record = true) :
    safeWindow since upperBound (first ++ record :: rest) =
      safeWindow since upperBound first ++ record :: safeWindow since upperBound rest := by
  simp [safeWindow, eligible]

/-- Dated observations have the same exact filtered sequence before and after seeking. -/
def datedWindow (since : Nat) (upperBound : Option Nat) (records : List Record) : List Record :=
  records.filter fun record => record.timestamp.isSome && admitted since upperBound record

theorem no_recent_record_is_not_an_admitted_date (since : Nat) (upperBound : Option Nat)
    (record : Record) (notRecent : recent since record = false) :
    (record.timestamp.isSome && admitted since upperBound record) = false := by
  cases dated : record.timestamp with
  | none => simp
  | some time =>
    have older : time < since := by simpa [recent, dated] using notRecent
    simp [admitted, old, dated, older]

theorem safe_seek_preserves_exact_dated_window (since : Nat) (upperBound : Option Nat)
    (records : List Record) (positive : ∀ record ∈ records, 0 < record.bytes) :
    datedWindow since upperBound (dropBytes (safeBoundary since records) records) =
      datedWindow since upperBound records := by
  obtain ⟨first, rest, split, offset, noneRecent⟩ := safe_boundary_is_complete_prefix since records
  have firstPositive : ∀ record ∈ first, 0 < record.bytes := by
    intro record member
    exact positive record (by simp [split, member])
  have empty : datedWindow since upperBound first = [] := by
    apply List.filter_eq_nil_iff.mpr
    intro record member
    simpa using no_recent_record_is_not_an_admitted_date since upperBound record
      (noneRecent record member)
  rw [offset, split, drop_bytes_preserves_complete_suffix first rest firstPositive]
  simp only [datedWindow, List.filter_append] at empty ⊢
  rw [empty, List.nil_append]

end PeriScribe.LogSeeking
