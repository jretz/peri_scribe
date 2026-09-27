import PeriScribe.CoordinateQuantization

namespace PeriScribe.NumericalPolicy

/-- Finite binary64 values are exact integers in units of the least subnormal. -/
def scale : Nat := 2 ^ 1074

/-- The binade selects 53 significant bits; subnormal spacing remains one unit. -/
def quantum (numerator denominator : Nat) : Nat :=
  2 ^ ((numerator / denominator).log2 + 1 - 53)

def roundedMagnitude (numerator denominator : Nat) : Int :=
  let spacing := quantum numerator denominator
  PeriScribe.CoordinateQuantization.nearest numerator (denominator * spacing) * spacing

def rounded (numerator : Int) (denominator : Nat) : Int :=
  let value := roundedMagnitude numerator.natAbs denominator
  if numerator < 0 then -value else value

theorem spacing_positive (numerator denominator : Nat) :
    0 < quantum numerator denominator := by
  exact Nat.two_pow_pos _

/-- Error is bounded by half the selected spacing, including underflow and ties. -/
theorem rounded_magnitude_half_spacing (numerator denominator : Nat)
    (positive : 0 < denominator) :
    2 * (numerator : Int) - denominator * quantum numerator denominator ≤
        2 * (roundedMagnitude numerator denominator * denominator) ∧
      2 * (roundedMagnitude numerator denominator * denominator) ≤
        2 * numerator + denominator * quantum numerator denominator := by
  have spacing := spacing_positive numerator denominator
  have bound := PeriScribe.CoordinateQuantization.nearest_half_step_error
    numerator (denominator * quantum numerator denominator)
    (by exact_mod_cast Nat.mul_pos positive spacing)
  simpa [roundedMagnitude, Int.mul_assoc, Int.mul_comm, Int.mul_left_comm] using bound

theorem rounded_magnitude_nonnegative (numerator denominator : Nat)
    (positive : 0 < denominator) : 0 ≤ roundedMagnitude numerator denominator := by
  have spacing := spacing_positive numerator denominator
  have nonnegative :=
    PeriScribe.CoordinateQuantization.encoded_upper_bound_keeps_stored_coordinate
      numerator (denominator * quantum numerator denominator) 0
      (by exact_mod_cast Nat.mul_pos positive spacing) (by simp)
  exact Int.mul_nonneg nonnegative (by omega)

theorem rounding_is_odd (numerator : Int) (denominator : Nat) :
    rounded (-numerator) denominator = -rounded numerator denominator := by
  by_cases zero : numerator = 0
  · simp [zero, rounded, roundedMagnitude, quantum,
      PeriScribe.CoordinateQuantization.nearest]
    split <;> (try split) <;> omega
  · simp only [rounded, Int.natAbs_neg]
    split <;> split <;> simp_all <;> omega

def subtract (left right : Int) : Int := rounded (left - right) 1
def multiply (left right : Int) : Int := rounded (left * right) scale
def divide (left right : Int) : Int :=
  if right < 0 then rounded (-left * scale) right.natAbs
  else rounded (left * scale) right.natAbs

def magnitude (value : Int) : Int := value.natAbs

theorem magnitude_neg (value : Int) : magnitude (-value) = magnitude value := by
  simp [magnitude]

theorem rounded_magnitude_exact (numerator : Int) (denominator : Nat)
    (positive : 0 < denominator) :
    magnitude (rounded numerator denominator) =
      roundedMagnitude numerator.natAbs denominator := by
  have nonnegative :=
    rounded_magnitude_nonnegative numerator.natAbs denominator positive
  unfold rounded
  split
  · rw [magnitude_neg]
    exact Int.natAbs_of_nonneg nonnegative
  · exact Int.natAbs_of_nonneg nonnegative

theorem subtraction_reverses_sign (left right : Int) :
    subtract right left = -subtract left right := by
  rw [subtract, show right - left = -(left - right) by omega, rounding_is_odd]
  rfl

/-- Match the relative-only close comparison, including rounded subtraction/products. -/
def close (left right tolerance : Int) : Bool :=
  let gap := magnitude (subtract left right)
  decide (gap ≤ magnitude (multiply tolerance right) ∨
    gap ≤ magnitude (multiply tolerance left))

theorem close_symmetric (left right tolerance : Int) :
    close left right tolerance = close right left tolerance := by
  simp only [close, subtraction_reverses_sign right left, magnitude_neg]
  simp [or_comm]

/-- A zero change never supplies the winning signal, even at a zero threshold. -/
def publish (change threshold tolerance : Int) : Bool :=
  decide (0 < magnitude change) &&
    (decide (threshold ≤ magnitude change) ||
      close (magnitude change) threshold tolerance)

theorem no_zero_signal (threshold tolerance : Int) :
    publish 0 threshold tolerance = false := by simp [publish, magnitude]

theorem growth_and_shrinkage_agree (change threshold tolerance : Int) :
    publish (-change) threshold tolerance = publish change threshold tolerance := by
  simp [publish, magnitude_neg]

theorem threshold_equality_publishes (threshold tolerance : Int)
    (positive : 0 < threshold) : publish threshold threshold tolerance = true := by
  have abs : magnitude threshold = threshold := by
    exact Int.natAbs_of_nonneg (by omega)
  simp [publish, abs, positive]

theorem above_threshold_publishes (change threshold tolerance : Int)
    (nonzero : 0 < magnitude change) (above : threshold ≤ magnitude change) :
    publish change threshold tolerance = true := by simp [publish, nonzero, above]

theorem below_threshold_requires_tolerance_witness (change threshold tolerance : Int)
    (below : magnitude change < threshold)
    (accepted : publish change threshold tolerance = true) :
    magnitude (subtract (magnitude change) threshold) ≤
        magnitude (multiply tolerance threshold) ∨
      magnitude (subtract (magnitude change) threshold) ≤
        magnitude (multiply tolerance (magnitude change)) := by
  simp only [publish, Bool.and_eq_true] at accepted
  simpa [close, show ¬threshold ≤ magnitude change by omega] using accepted.2

theorem outside_both_tolerance_bounds_rejected (change threshold tolerance : Int)
    (below : magnitude change < threshold)
    (thresholdGap : magnitude (multiply tolerance threshold) <
      magnitude (subtract (magnitude change) threshold))
    (changeGap : magnitude (multiply tolerance (magnitude change)) <
      magnitude (subtract (magnitude change) threshold)) :
    publish change threshold tolerance = false := by
  simp [publish, close, show ¬threshold ≤ magnitude change by omega,
    show ¬magnitude (subtract (magnitude change) threshold) ≤
      magnitude (multiply tolerance threshold) by omega,
    show ¬magnitude (subtract (magnitude change) threshold) ≤
      magnitude (multiply tolerance (magnitude change)) by omega]

/-- Rounding cannot admit a change outside the tolerance plus half-spacing margin. -/
theorem beyond_rounding_margin_rejected (change threshold tolerance bound : Int)
    (below : magnitude change < threshold)
    (bounds : magnitude (multiply tolerance threshold) ≤ bound ∧
      magnitude (multiply tolerance (magnitude change)) ≤ bound)
    (outside : 2 * ((magnitude change - threshold).natAbs : Int) -
      quantum (magnitude change - threshold).natAbs 1 > 2 * bound) :
    publish change threshold tolerance = false := by
  have rounding := rounded_magnitude_half_spacing
    (magnitude change - threshold).natAbs 1 (by omega)
  have exact := rounded_magnitude_exact (magnitude change - threshold) 1 (by omega)
  apply outside_both_tolerance_bounds_rejected change threshold tolerance below
  · simp only [subtract, exact]
    simp only [Int.natCast_one, Int.one_mul, Int.mul_one] at rounding
    omega
  · simp only [subtract, exact]
    simp only [Int.natCast_one, Int.one_mul, Int.mul_one] at rounding
    omega

/-- Fractional area policy consumes the same rounded operations as unit quantities. -/
def takeover (mapped conversion report reportFactor mappedFactor baseline minimum
    significant rapid : Int)
    (hasBaseline newer : Bool) (age : Int) (confirmations : Nat) : Bool :=
  newer && (!hasBaseline || decide (baseline < report)) &&
    decide (minimum ≤ subtract report (multiply mapped conversion)) &&
    (decide (259200 ≤ age ∧ multiply (multiply mapped significant) mappedFactor ≤
      multiply report reportFactor) ||
      decide (86400 ≤ age ∧ multiply (multiply mapped rapid) mappedFactor ≤
        multiply report reportFactor ∧
        2 ≤ confirmations))

theorem numerical_takeover_needs_later_evidence
    (mapped conversion report reportFactor mappedFactor baseline minimum
      significant rapid : Int)
    (hasBaseline newer : Bool) (age : Int) (confirmations : Nat)
    (accepted : takeover mapped conversion report reportFactor mappedFactor baseline
      minimum significant rapid
      hasBaseline newer age confirmations = true) : newer = true := by
  simp only [takeover, Bool.and_eq_true] at accepted
  exact accepted.1.1.1

theorem numerical_takeover_cannot_precede_one_day
    (mapped conversion report reportFactor mappedFactor baseline minimum
      significant rapid : Int)
    (hasBaseline newer : Bool) (age : Int) (confirmations : Nat)
    (accepted : takeover mapped conversion report reportFactor mappedFactor baseline
      minimum significant rapid
      hasBaseline newer age confirmations = true) : 86400 ≤ age := by
  simp only [takeover, Bool.and_eq_true, Bool.or_eq_true, decide_eq_true_eq] at accepted
  rcases accepted.2 with ordinary | early <;> omega

def acceptReport (previous current minimum significant : Int)
    (confirmed : Bool) : Bool :=
  confirmed || decide (¬(multiply current significant < previous ∧
    minimum ≤ subtract previous current))

theorem confirmed_fractional_corrections_accepted
    (previous current minimum significant : Int) :
    acceptReport previous current minimum significant true = true := by
  simp [acceptReport]

end PeriScribe.NumericalPolicy
