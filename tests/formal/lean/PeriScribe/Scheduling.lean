import Std

namespace PeriScribe.Scheduling

/-- UTC elapsed seconds are negative when checkpoints lie in the future. -/
def due (interval : Nat) (elapsed : Option Int) : Bool :=
  if interval = 0 then true
  else match elapsed with
    | none => true
    | some age => decide ((interval : Int) ≤ age)

theorem zero_interval_is_always_due (elapsed : Option Int) : due 0 elapsed = true := by
  simp [due]

theorem missing_checkpoint_is_due (interval : Nat) : due interval none = true := by
  simp [due]

theorem future_checkpoint_waits (interval : Nat) (elapsed : Int)
    (positive : 0 < interval) (future : elapsed < 0) :
    due interval (some elapsed) = false := by
  simp [due, Nat.ne_of_gt positive]
  omega

theorem due_stays_due_as_time_advances (interval : Nat) (earlier later : Int)
    (advances : earlier ≤ later) (wasDue : due interval (some earlier) = true) :
    due interval (some later) = true := by
  by_cases zero : interval = 0
  · simp [due, zero]
  · simp_all [due]
    omega

end PeriScribe.Scheduling
