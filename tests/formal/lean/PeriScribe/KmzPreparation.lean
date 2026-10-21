import Std

namespace PeriScribe.KmzPreparation

structure Identity where
  fullGeneration : Nat
  differentialGeneration : Nat
  fireIndex : Nat
  minimumArea : Nat
  areaPolicy : Nat
  runtime : Nat
  deriving DecidableEq, Repr

def identityMatches (stored current : Identity) : Bool := decide (stored = current)

theorem identity_matches_exact_inputs (stored current : Identity) :
    identityMatches stored current = true ↔ stored = current := by
  simp [identityMatches]

theorem matching_identity_preserves_every_dependency (stored current : Identity)
    (matching : identityMatches stored current = true) :
    stored.fullGeneration = current.fullGeneration ∧
      stored.differentialGeneration = current.differentialGeneration ∧
      stored.fireIndex = current.fireIndex ∧ stored.minimumArea = current.minimumArea ∧
      stored.areaPolicy = current.areaPolicy ∧
      stored.runtime = current.runtime := by
  have same := (identity_matches_exact_inputs stored current).mp matching
  cases same
  exact ⟨rfl, rfl, rfl, rfl, rfl, rfl⟩

def demands (groups : List (List Nat)) : List Nat := groups.filterMap List.getLast?

theorem latest_position_is_demanded (groups : List (List Nat)) (group : List Nat)
    (position : Nat) (selected : group ∈ groups) (latest : group.getLast? = some position) :
    position ∈ demands groups := by
  exact List.mem_filterMap.mpr ⟨group, selected, latest⟩

theorem empty_groups_demand_nothing : demands [[], []] = [] := by
  rfl

def projectedValue (rows : Nat → α) (positions : List Nat) (position : Nat) : Option α :=
  if position ∈ positions then some (rows position) else none

theorem projection_preserves_latest_value (rows : Nat → α) (groups : List (List Nat))
    (group : List Nat) (position : Nat) (selected : group ∈ groups)
    (latest : group.getLast? = some position) :
    projectedValue rows (demands groups) position = some (rows position) := by
  have present := latest_position_is_demanded groups group position selected latest
  simp [projectedValue, present]

theorem projection_omits_undemanded_values (rows : Nat → α) (positions : List Nat)
    (position : Nat) (absent : position ∉ positions) :
    projectedValue rows positions position = none := by
  simp [projectedValue, absent]

structure History where
  key : Nat
  payload : Nat
  qualifies : Bool
  deriving DecidableEq, Repr

def qualifyingHistories (rows : List History) : List History := rows.filter History.qualifies

theorem qualifying_subset_is_exact (rows : List History) (row : History) :
    row ∈ qualifyingHistories rows ↔ row ∈ rows ∧ row.qualifies = true := by
  simp [qualifyingHistories]

theorem qualifying_subset_preserves_complete_history (rows : List History) (row : History)
    (present : row ∈ rows) (qualified : row.qualifies = true) :
    row ∈ qualifyingHistories rows := by
  exact (qualifying_subset_is_exact rows row).mpr ⟨present, qualified⟩

end PeriScribe.KmzPreparation
