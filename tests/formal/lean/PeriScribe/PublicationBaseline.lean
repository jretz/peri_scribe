import Std

namespace PeriScribe.PublicationBaseline

inductive Owner where
  | identified (identifier : Nat)
  | anonymous (name : Nat)
  deriving DecidableEq, BEq, ReflBEq, LawfulBEq, Repr

structure IndexEntry where
  identifier : Option Nat
  aliases : List Nat
  name : Nat
  deriving Repr

def identifiers (entry : IndexEntry) : List Nat :=
  entry.identifier.toList ++ entry.aliases

def nameMatch (owner : Owner) (entry : IndexEntry) : Bool :=
  match owner with
  | .identified _ => false
  | .anonymous name => entry.identifier.isNone && entry.name == name

def visible (index : List IndexEntry) (owner : Owner) (aliases : List Nat) : Bool :=
  index.any (fun entry =>
    aliases.any (identifiers entry).contains || nameMatch owner entry)

theorem visibility_has_index_witness (index : List IndexEntry) (owner : Owner)
    (aliases : List Nat) : visible index owner aliases = true ↔
      ∃ entry ∈ index, (∃ alias ∈ aliases, alias ∈ identifiers entry) ∨
        nameMatch owner entry = true := by
  simp [visible, List.any_eq_true]

theorem visibility_monotone_in_aliases (index : List IndexEntry) (owner : Owner)
    (before after : List Nat) (subset : ∀ alias ∈ before, alias ∈ after)
    (wasVisible : visible index owner before = true) :
    visible index owner after = true := by
  obtain ⟨entry, present, matchEntry⟩ :=
    (visibility_has_index_witness index owner before).mp wasVisible
  apply (visibility_has_index_witness index owner after).mpr
  refine ⟨entry, present, ?_⟩
  rcases matchEntry with ⟨alias, member, recognized⟩ | byName
  · exact Or.inl ⟨alias, subset alias member, recognized⟩
  · exact Or.inr byName

theorem identified_names_do_not_confer_visibility (identifier : Nat)
    (entry : IndexEntry) :
    nameMatch (.identified identifier) entry = false := rfl

theorem anonymous_names_require_anonymous_entry (name : Nat) (entry : IndexEntry)
    (matched : nameMatch (.anonymous name) entry = true) :
    entry.identifier = none ∧ entry.name = name := by
  simpa [nameMatch] using matched

structure Source where
  file : Nat
  object : Option Nat
  aliases : List Nat
  identity : Nat
  deriving DecidableEq, Repr

structure Row where
  identifier : Option Nat
  name : Nat
  aliases : List Nat
  file : Nat
  object : Option Nat
  deriving Repr

def owner (row : Row) : Owner :=
  match row.identifier with
  | some identifier => .identified identifier
  | none => .anonymous row.name

structure Evidence where
  owner : Owner
  name : Nat
  aliases : List Nat
  source : Nat
  deriving DecidableEq, Repr

def matchingSources (sources : List Source) (row : Row) : List Source :=
  sources.filter (fun source => source.file == row.file && source.object == row.object)

def resolve (sources : List Source) (row : Row) : Option Evidence :=
  match matchingSources sources row with
  | [source] => some ⟨owner row, row.name,
      row.identifier.toList ++ row.aliases ++ source.aliases, source.identity⟩
  | _ => none

theorem resolved_source_is_unique (sources : List Source) (row : Row)
    (evidence : Evidence) (resolved : resolve sources row = some evidence) :
    ∃ source, matchingSources sources row = [source] ∧
      evidence.source = source.identity := by
  unfold resolve at resolved
  cases found : matchingSources sources row with
  | nil => simp [found] at resolved
  | cons source rest =>
    cases rest with
    | nil =>
      refine ⟨source, rfl, ?_⟩
      simpa [found] using
        congrArg (fun value => value.map Evidence.source) resolved.symm
    | cons => simp [found] at resolved

theorem resolved_owner_agrees_with_displayed_row (sources : List Source) (row : Row)
    (evidence : Evidence) (resolved : resolve sources row = some evidence) :
    evidence.owner = owner row := by
  unfold resolve at resolved
  cases found : matchingSources sources row with
  | nil => simp [found] at resolved
  | cons source rest =>
    cases rest with
    | nil =>
      simpa [found] using
        congrArg (fun value => value.map Evidence.owner) resolved.symm
    | cons => simp [found] at resolved

def resolveAll (sources : List Source) : List Row → Option (List Evidence)
  | [] => some []
  | row :: rest => do
    let evidence ← resolve sources row
    let others ← resolveAll sources rest
    pure (evidence :: others)

theorem invalid_source_rejects_complete_collection (sources : List Source)
    (rows : List Row) (row : Row) (present : row ∈ rows)
    (invalid : resolve sources row = none) : resolveAll sources rows = none := by
  induction rows with
  | nil => simp at present
  | cons first rest ih =>
    rcases List.mem_cons.mp present with same | later
    · subst row
      simp [resolveAll, invalid]
    · simp [resolveAll, ih later]

theorem resolved_evidence_has_displayed_row (sources : List Source) (rows : List Row)
    (joined : List Evidence) (evidence : Evidence)
    (success : resolveAll sources rows = some joined) (member : evidence ∈ joined) :
    ∃ row ∈ rows, resolve sources row = some evidence := by
  induction rows generalizing joined with
  | nil =>
    have empty : [] = joined := by simpa [resolveAll] using success
    simp [← empty] at member
  | cons first rest ih =>
    cases current : resolve sources first with
    | none => simp [resolveAll, current] at success
    | some resolved =>
      cases remaining : resolveAll sources rest with
      | none => simp [resolveAll, current, remaining] at success
      | some others =>
        have eq : resolved :: others = joined := by
          simpa [resolveAll, current, remaining] using success
        rw [← eq] at member
        rcases List.mem_cons.mp member with same | later
        · exact ⟨first, by simp, by simpa [same] using current⟩
        · obtain ⟨row, present, identified⟩ := ih others remaining later
          exact ⟨row, by simp [present], identified⟩

def aliasesOf (previous : Option Evidence) : List Nat :=
  (previous.map Evidence.aliases).getD []

def accumulate (previous : Option Evidence) (current : Evidence) : Option Evidence :=
  some { current with aliases := aliasesOf previous ++ current.aliases }

def fold : List Evidence → Option Evidence → Option Evidence
  | [], previous => previous
  | current :: rest, previous => fold rest (accumulate previous current)

def forOwner (rows : List Evidence) (key : Owner) : List Evidence :=
  rows.filter (fun row => row.owner == key)

def baseline (rows : List Evidence) (key : Owner) : Option Evidence :=
  fold (forOwner rows key) none

theorem fold_aliases_exact (rows : List Evidence) (previous : Option Evidence) :
    aliasesOf (fold rows previous) =
      aliasesOf previous ++ rows.flatMap Evidence.aliases := by
  induction rows generalizing previous with
  | nil => simp [fold]
  | cons current rest ih =>
    rw [fold, ih]
    simp [accumulate, aliasesOf, List.append_assoc]

theorem aliases_exactly_owned_evidence (rows : List Evidence) (key : Owner)
    (alias : Nat) : alias ∈ aliasesOf (baseline rows key) ↔
      ∃ row ∈ rows, row.owner = key ∧ alias ∈ row.aliases := by
  unfold baseline
  rw [fold_aliases_exact]
  simp [aliasesOf, forOwner, List.mem_flatMap, and_assoc]

theorem fold_append (before after : List Evidence) (previous : Option Evidence) :
    fold (before ++ after) previous = fold after (fold before previous) := by
  induction before generalizing previous with
  | nil => rfl
  | cons first rest ih => simpa [fold] using ih (accumulate previous first)

theorem final_row_supplies_source_and_name (before : List Evidence) (last : Evidence)
    (previous : Option Evidence) :
    (fold (before ++ [last]) previous).map (fun row => (row.source, row.name)) =
      some (last.source, last.name) := by
  simp [fold_append, fold, accumulate]

theorem fold_agrees_with_last_row (rows : List Evidence) (previous : Option Evidence) :
    (fold rows previous).map (fun row => (row.source, row.name)) =
      match rows.getLast? with
      | none => previous.map (fun row => (row.source, row.name))
      | some last => some (last.source, last.name) := by
  induction rows generalizing previous with
  | nil => rfl
  | cons current rest ih =>
    rw [fold, ih, List.getLast?_cons]
    cases rest.getLast? <;> simp [accumulate]

theorem final_row_source_has_input_witness (rows : List Evidence) (source name : Nat)
    (selected : (fold rows none).map (fun row => (row.source, row.name)) =
      some (source, name)) :
    ∃ row ∈ rows, row.source = source ∧ row.name = name := by
  rw [fold_agrees_with_last_row] at selected
  cases found : rows.getLast? with
  | none => simp [found] at selected
  | some last =>
    have same : (last.source, last.name) = (source, name) := by
      simpa [found] using selected
    exact ⟨last, List.mem_of_getLast? found, by simpa using same⟩

theorem fold_missing_iff (rows : List Evidence) (previous : Option Evidence) :
    fold rows previous = none ↔ rows = [] ∧ previous = none := by
  induction rows generalizing previous with
  | nil => simp [fold]
  | cons current rest ih => simp [fold, ih, accumulate]

theorem nonempty_rows_have_baseline (rows : List Evidence) :
    fold rows none = none ↔ rows = [] := by
  simp [fold_missing_iff]

theorem baseline_exists_exactly_for_owner (rows : List Evidence) (key : Owner) :
    baseline rows key = none ↔ ¬ ∃ row ∈ rows, row.owner = key := by
  simp [baseline, nonempty_rows_have_baseline, forOwner, List.filter_eq_nil_iff]

theorem final_matching_row_supplies_source (before after : List Evidence)
    (last : Evidence) (key : Owner) (owned : last.owner = key)
    (unrelated : ∀ row ∈ after, row.owner ≠ key) :
    (baseline (before ++ last :: after) key).map (fun row => (row.source, row.name)) =
      some (last.source, last.name) := by
  have empty : forOwner after key = [] := by
    simpa [forOwner, List.filter_eq_nil_iff] using unrelated
  have filtered : forOwner (before ++ last :: after) key =
      forOwner before key ++ [last] := by
    simp only [forOwner, List.filter_append, List.filter_cons, owned, beq_self_eq_true]
    simp only [ite_true]
    change forOwner before key ++ last :: forOwner after key = _
    rw [empty]
    rfl
  rw [baseline, filtered]
  exact final_row_supplies_source_and_name _ _ _

theorem aliases_monotone_across_publication_rows (before after : List Evidence)
    (key : Owner) (alias : Nat) (present : alias ∈ aliasesOf (baseline before key)) :
    alias ∈ aliasesOf (baseline (before ++ after) key) := by
  obtain ⟨row, member, owned, contained⟩ :=
    (aliases_exactly_owned_evidence before key alias).mp present
  exact (aliases_exactly_owned_evidence (before ++ after) key alias).mpr
    ⟨row, by simp [member], owned, contained⟩

theorem visibility_persists_across_publication_rows (index : List IndexEntry)
    (before after : List Evidence) (key : Owner)
    (included : visible index key (aliasesOf (baseline before key)) = true) :
    visible index key (aliasesOf (baseline (before ++ after) key)) = true := by
  exact visibility_monotone_in_aliases index key _ _
    (aliases_monotone_across_publication_rows before after key) included

def uniqueOwners : List Owner → List Owner
  | [] => []
  | first :: rest => first :: (uniqueOwners rest).filter (· != first)

theorem unique_owners_membership (owners : List Owner) (key : Owner) :
    key ∈ uniqueOwners owners ↔ key ∈ owners := by
  induction owners with
  | nil => simp [uniqueOwners]
  | cons first rest ih =>
    by_cases same : key = first <;> simp [uniqueOwners, ih, same]

theorem unique_owners_nodup (owners : List Owner) : (uniqueOwners owners).Nodup := by
  induction owners with
  | nil => simp [uniqueOwners]
  | cons first rest ih =>
    simp only [uniqueOwners, List.nodup_cons]
    exact ⟨by simp, List.Pairwise.filter _ ih⟩

def keys (rows : List Evidence) : List Owner := uniqueOwners (rows.map Evidence.owner)

theorem result_owners_are_unique (rows : List Evidence) : (keys rows).Nodup := by
  exact unique_owners_nodup _

theorem result_owners_are_exact (rows : List Evidence) (key : Owner) :
    key ∈ keys rows ↔ ∃ row ∈ rows, row.owner = key := by
  simp [keys, unique_owners_membership, List.mem_map]

def displayed (index : List IndexEntry) (key : Owner) (evidence : Evidence) :
    Option Nat :=
  if visible index key evidence.aliases then some evidence.source else none

theorem excluded_owner_has_no_area_baseline (index : List IndexEntry) (key : Owner)
    (evidence : Evidence) (excluded : visible index key evidence.aliases = false) :
    displayed index key evidence = none := by simp [displayed, excluded]

theorem displayed_source_is_final_raw_source (index : List IndexEntry) (key : Owner)
    (evidence : Evidence) (source : Nat)
    (selected : displayed index key evidence = some source) :
    source = evidence.source ∧ visible index key evidence.aliases = true := by
  unfold displayed at selected
  split at selected <;> simp_all

theorem complete_baseline_has_unique_raw_witness (sources : List Source)
    (rows : List Row) (joined : List Evidence) (key : Owner) (evidence : Evidence)
    (resolved : resolveAll sources rows = some joined)
    (selected : baseline joined key = some evidence) :
    ∃ row ∈ rows, owner row = key ∧ ∃ source, matchingSources sources row = [source] ∧
      source.identity = evidence.source := by
  have projected : (fold (forOwner joined key) none).map
      (fun row => (row.source, row.name)) = some (evidence.source, evidence.name) := by
    change (baseline joined key).map _ = _
    simp [selected]
  obtain ⟨last, present, sameSource, _⟩ :=
    final_row_source_has_input_witness _ _ _ projected
  obtain ⟨row, member, identified⟩ := resolved_evidence_has_displayed_row sources rows
    joined last resolved (List.mem_filter.mp present).1
  obtain ⟨source, unique, same⟩ := resolved_source_is_unique sources row last identified
  have owned : last.owner = key := by simpa using (List.mem_filter.mp present).2
  have rowOwner := resolved_owner_agrees_with_displayed_row sources row last identified
  exact ⟨row, member, rowOwner.symm.trans owned, source, unique,
    same.symm.trans sameSource⟩

end PeriScribe.PublicationBaseline
