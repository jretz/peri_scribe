import PeriScribe.RetainedSourceIndex

namespace PeriScribe.SourceProvenance

/-- Keys include the lexical directory and path; values contain no filesystem evidence. -/
def Valid {Key Value : Type} (derive : Key → Value) (memo : Key → Option Value) : Prop :=
  ∀ key value, memo key = some value → value = derive key

def result {Key Value : Type} (derive : Key → Value)
    (memo : Key → Option Value) (key : Key) : Value :=
  (memo key).getD (derive key)

def remember {Key Value : Type} [DecidableEq Key] (memo : Key → Option Value)
    (key : Key) (value : Value) : Key → Option Value :=
  fun query => if query = key then some value else memo query

theorem result_equals_derivation {Key Value : Type} (derive : Key → Value)
    (memo : Key → Option Value) (valid : Valid derive memo) (key : Key) :
    result derive memo key = derive key := by
  cases retained : memo key with
  | none => simp [result, retained]
  | some value => simpa [result, retained] using valid key value retained

theorem remember_preserves_validity {Key Value : Type} [DecidableEq Key]
    (derive : Key → Value) (memo : Key → Option Value) (valid : Valid derive memo)
    (key : Key) : Valid derive (remember memo key (result derive memo key)) := by
  intro query value retained
  by_cases same : query = key
  · subst query
    simp [remember] at retained
    exact retained.symm.trans (result_equals_derivation derive memo valid key)
  · exact valid query value (by simpa [remember, same] using retained)

def trace {Key Value : Type} [DecidableEq Key] (derive : Key → Value)
    (memo : Key → Option Value) : List Key → List Value
  | [] => []
  | key :: rest =>
    let value := result derive memo key
    value :: trace derive (remember memo key value) rest

/-- Repeated keys retain their positions and multiplicity under any pure derivation. -/
theorem trace_equals_complete_map {Key Value : Type} [DecidableEq Key]
    (derive : Key → Value) (memo : Key → Option Value) (valid : Valid derive memo)
    (keys : List Key) : trace derive memo keys = keys.map derive := by
  induction keys generalizing memo with
  | nil => rfl
  | cons key rest induction =>
    simp only [trace, List.map_cons]
    rw [induction _ (remember_preserves_validity derive memo valid key),
      result_equals_derivation derive memo valid key]

theorem empty_memo_valid {Key Value : Type} (derive : Key → Value) :
    Valid derive (fun _ => none) := by
  intro key value retained
  contradiction

/-- Construction starts with individually validated typed rows and checks uniqueness. -/
def validating {Row Reference Incidence : Type} [DecidableEq Reference]
    [DecidableEq Incidence] (reference : Row → Reference)
    (canonical : List Row → List Incidence) (rows : List Row)
    (reverse : List Incidence) : Option (List Row × List Incidence) :=
  if (rows.map reference).Nodup ∧ reverse = canonical rows then some (rows, reverse)
  else none

def constructed {Row Reference Incidence : Type} [DecidableEq Reference]
    (reference : Row → Reference) (canonical : List Row → List Incidence)
    (rows : List Row) : Option (List Row × List Incidence) :=
  if (rows.map reference).Nodup then some (rows, canonical rows) else none

/-- The canonical reverse need not be reconstructed by the aggregate validator. -/
theorem constructed_equals_validating {Row Reference Incidence : Type}
    [DecidableEq Reference] [DecidableEq Incidence] (reference : Row → Reference)
    (canonical : List Row → List Incidence) (rows : List Row) :
    constructed reference canonical rows =
      validating reference canonical rows (canonical rows) := by
  simp [constructed, validating]

/-- Existing path-closure semantics justify returning before adjacency construction. -/
theorem no_changed_seeds_no_affected_rows (current : List Nat)
    (before after : List Grouping.Edge) :
    RetainedSourceIndex.affected current before after [] = [] := by
  simp [RetainedSourceIndex.affected, RetainedSourceIndex.isAffected]

end PeriScribe.SourceProvenance
