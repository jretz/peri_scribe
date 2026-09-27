import Std

namespace PeriScribe.Scoring

/-- Thresholds and awarded points are exact natural numbers at this policy boundary. -/
abbrev Tier := Nat × Nat

def tiered (value : Nat) : List Tier → Nat
  | [] => 0
  | (threshold, points) :: rest =>
    if threshold ≤ value then points else tiered value rest

/-- Earlier tiers must award at least as many points as any later tier. -/
def Ordered : List Tier → Prop
  | [] => True
  | first :: rest => (∀ tier ∈ rest, tier.2 ≤ first.2) ∧ Ordered rest

theorem tiered_bounded (tiers : List Tier) (value bound : Nat)
    (bounded : ∀ tier ∈ tiers, tier.2 ≤ bound) : tiered value tiers ≤ bound := by
  induction tiers with
  | nil => simp [tiered]
  | cons first rest induction =>
    obtain ⟨threshold, points⟩ := first
    simp only [tiered]
    split
    · exact bounded (threshold, points) List.mem_cons_self
    · apply induction
      intro tier present
      exact bounded tier (List.mem_cons_of_mem _ present)

theorem tiered_monotone (tiers : List Tier) (ordered : Ordered tiers)
    (smaller larger : Nat) (increasing : smaller ≤ larger) :
    tiered smaller tiers ≤ tiered larger tiers := by
  induction tiers with
  | nil => simp [tiered]
  | cons first rest induction =>
    obtain ⟨threshold, points⟩ := first
    by_cases reached : threshold ≤ smaller
    · have largerReached : threshold ≤ larger := Nat.le_trans reached increasing
      simp [tiered, reached, largerReached]
    · by_cases largerReached : threshold ≤ larger
      · simp [tiered, reached, largerReached]
        exact tiered_bounded rest smaller points ordered.1
      · simp [tiered, reached, largerReached]
        exact induction ordered.2

def sizeTiers : List Tier :=
  [(100000, 5), (50000, 4), (25000, 3), (10000, 2), (1000, 1)]

def growthTiers : List Tier := [(50000, 4), (25000, 3), (10000, 2), (5000, 1)]

def firstMappingTiers : List Tier := [(5000, 3), (1000, 2), (100, 1)]

def buildingTiers : List Tier := [(1000, 4), (250, 3), (50, 2), (5, 1)]

theorem size_tiers_ordered : Ordered sizeTiers := by
  simp [Ordered, sizeTiers]

theorem growth_tiers_ordered : Ordered growthTiers := by
  simp [Ordered, growthTiers]

theorem first_mapping_tiers_ordered : Ordered firstMappingTiers := by
  simp [Ordered, firstMappingTiers]

theorem building_tiers_ordered : Ordered buildingTiers := by
  simp [Ordered, buildingTiers]

def total (size growth firstMapping buildings : Nat) (evacuation : Bool)
    (importance : Nat) : Nat :=
  27 * tiered size sizeTiers + 15 * tiered growth growthTiers +
    11 * tiered firstMapping firstMappingTiers + 4 * tiered buildings buildingTiers +
    (if evacuation then 33 else 0) + 120 * importance

theorem total_bounded (size growth firstMapping buildings importance : Nat)
    (evacuation : Bool) (validImportance : importance ≤ 3) :
    total size growth firstMapping buildings evacuation importance ≤ 637 := by
  have sizeBound : tiered size sizeTiers ≤ 5 :=
    tiered_bounded sizeTiers size 5 (by simp [sizeTiers])
  have growthBound : tiered growth growthTiers ≤ 4 :=
    tiered_bounded growthTiers growth 4 (by simp [growthTiers])
  have firstBound : tiered firstMapping firstMappingTiers ≤ 3 :=
    tiered_bounded firstMappingTiers firstMapping 3 (by simp [firstMappingTiers])
  have buildingBound : tiered buildings buildingTiers ≤ 4 :=
    tiered_bounded buildingTiers buildings 4 (by simp [buildingTiers])
  unfold total
  cases evacuation <;> simp only [Bool.false_eq_true, ↓reduceIte] <;> omega

theorem total_monotone_in_signals
    (size growth firstMapping buildings importance : Nat)
    (newSize newGrowth newFirstMapping newBuildings newImportance : Nat)
    (evacuation : Bool)
    (sizeGrows : size ≤ newSize) (growthGrows : growth ≤ newGrowth)
    (firstGrows : firstMapping ≤ newFirstMapping)
    (buildingsGrow : buildings ≤ newBuildings)
    (importanceGrows : importance ≤ newImportance) :
    total size growth firstMapping buildings evacuation importance ≤
      total newSize newGrowth newFirstMapping newBuildings
        evacuation newImportance := by
  have := tiered_monotone sizeTiers size_tiers_ordered size newSize sizeGrows
  have := tiered_monotone growthTiers growth_tiers_ordered growth newGrowth growthGrows
  have := tiered_monotone firstMappingTiers first_mapping_tiers_ordered
    firstMapping newFirstMapping firstGrows
  have := tiered_monotone buildingTiers building_tiers_ordered
    buildings newBuildings buildingsGrow
  unfold total
  omega

end PeriScribe.Scoring
