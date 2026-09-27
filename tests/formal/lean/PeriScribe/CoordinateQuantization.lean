import Std

namespace PeriScribe.CoordinateQuantization

/-- Euclidean division makes negative half ties follow the same even-integer rule. -/
def nearest (numerator denominator : Int) : Int :=
  let quotient := numerator / denominator
  let remainder := numerator % denominator
  if 2 * remainder < denominator then quotient
  else if denominator < 2 * remainder then quotient + 1
  else if quotient % 2 = 0 then quotient else quotient + 1

theorem nearest_half_step_error (numerator denominator : Int)
    (positive : 0 < denominator) :
    2 * numerator - denominator ≤ 2 * (nearest numerator denominator * denominator) ∧
      2 * (nearest numerator denominator * denominator) ≤
        2 * numerator + denominator := by
  have remainderLower := Int.emod_nonneg numerator (by omega : denominator ≠ 0)
  have remainderUpper := Int.emod_lt_of_pos numerator positive
  have decomposition := Int.ediv_mul_add_emod numerator denominator
  simp only [nearest]
  split <;> rename_i low
  · omega
  · split <;> rename_i high
    · simp only [Int.add_mul, Int.one_mul]
      omega
    · split
      · omega
      · simp only [Int.add_mul, Int.one_mul]
        omega

theorem integral_coordinates_are_fixed (value denominator : Int)
    (positive : 0 < denominator) :
    nearest (value * denominator) denominator = value := by
  simp [nearest, Int.mul_ediv_cancel _ (by omega : denominator ≠ 0), positive]

theorem even_half_tie_stays_lower (quotient denominator : Int)
    (positive : 0 < denominator) (even : quotient % 2 = 0) :
    nearest (quotient * (2 * denominator) + denominator) (2 * denominator) =
      quotient := by
  have components :
      (quotient * (2 * denominator) + denominator) / (2 * denominator) = quotient ∧
      (quotient * (2 * denominator) + denominator) % (2 * denominator) = denominator :=
    (Int.ediv_emod_unique (by omega : 0 < 2 * denominator)).mpr
      ⟨by simp [Int.mul_comm, Int.add_comm], by omega, by omega⟩
  simp [nearest, components.1, components.2, even]

theorem odd_half_tie_rounds_up (quotient denominator : Int)
    (positive : 0 < denominator) (odd : quotient % 2 ≠ 0) :
    nearest (quotient * (2 * denominator) + denominator) (2 * denominator) =
      quotient + 1 := by
  have components :
      (quotient * (2 * denominator) + denominator) / (2 * denominator) = quotient ∧
      (quotient * (2 * denominator) + denominator) % (2 * denominator) = denominator :=
    (Int.ediv_emod_unique (by omega : 0 < 2 * denominator)).mpr
      ⟨by simp [Int.mul_comm, Int.add_comm], by omega, by omega⟩
  simp [nearest, components.1, components.2, odd]

/-- Integer envelope endpoints do not drop an enclosed stored grid coordinate. -/
theorem encoded_lower_bound_keeps_stored_coordinate (numerator denominator stored : Int)
    (positive : 0 < denominator) (inside : numerator ≤ stored * denominator) :
    nearest numerator denominator ≤ stored := by
  have error := nearest_half_step_error numerator denominator positive
  by_cases result : nearest numerator denominator ≤ stored
  · exact result
  have step : stored + 1 ≤ nearest numerator denominator := by omega
  have bound := Int.mul_le_mul_of_nonneg_right step (by omega : 0 ≤ denominator)
  simp only [Int.add_mul, Int.one_mul] at bound
  omega

theorem encoded_upper_bound_keeps_stored_coordinate (numerator denominator stored : Int)
    (positive : 0 < denominator) (inside : stored * denominator ≤ numerator) :
    stored ≤ nearest numerator denominator := by
  have error := nearest_half_step_error numerator denominator positive
  by_cases result : stored ≤ nearest numerator denominator
  · exact result
  have step : nearest numerator denominator + 1 ≤ stored := by omega
  have bound := Int.mul_le_mul_of_nonneg_right step (by omega : 0 ≤ denominator)
  simp only [Int.add_mul, Int.one_mul] at bound
  omega

theorem encoded_envelope_is_conservative (low high denominator stored : Int)
    (positive : 0 < denominator)
    (inside : low ≤ stored * denominator ∧ stored * denominator ≤ high) :
    nearest low denominator ≤ stored ∧ stored ≤ nearest high denominator :=
  ⟨encoded_lower_bound_keeps_stored_coordinate low denominator stored positive inside.1,
    encoded_upper_bound_keeps_stored_coordinate high denominator stored
      positive inside.2⟩

theorem valid_geographic_coordinates_stay_in_range (numerator denominator limit : Int)
    (positive : 0 < denominator)
    (valid : -limit * denominator ≤ numerator ∧ numerator ≤ limit * denominator) :
    -limit ≤ nearest numerator denominator ∧ nearest numerator denominator ≤ limit :=
  ⟨encoded_upper_bound_keeps_stored_coordinate numerator denominator (-limit)
      positive valid.1,
    encoded_lower_bound_keeps_stored_coordinate numerator denominator limit
      positive valid.2⟩

theorem encoded_geographic_intermediates_fit_int32 (longitude latitude : Int)
    (validLongitude : -18000000 ≤ longitude ∧ longitude ≤ 18000000)
    (validLatitude : -9000000 ≤ latitude ∧ latitude ≤ 9000000) :
    -2147483648 ≤ longitude ∧ longitude ≤ 2147483647 ∧
      -2147483648 ≤ latitude ∧ latitude ≤ 2147483647 ∧
      0 ≤ longitude + 18000000 ∧ longitude + 18000000 ≤ 2147483647 ∧
      0 ≤ latitude + 9000000 ∧ latitude + 9000000 ≤ 2147483647 := by omega

end PeriScribe.CoordinateQuantization
