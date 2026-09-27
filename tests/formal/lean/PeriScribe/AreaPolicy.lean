import Std

namespace PeriScribe.AreaPolicy

/-- Exact integer acres and seconds isolate the default policy from numerical geometry.
    Confirmations count distinct eligible report times, after source reconciliation. -/
structure Evidence where
  mapped : Nat
  reported : Nat
  reportNewer : Bool
  baseline : Option Nat
  age : Int
  confirmations : Nat
  deriving Repr

/-- Rational thresholds are cross-multiplied, avoiding rounding at policy boundaries. -/
def Eligible (evidence : Evidence) : Prop :=
  evidence.reportNewer = true ∧
  (match evidence.baseline with
    | none => True
    | some baseline => baseline < evidence.reported) ∧
  evidence.mapped + 10 ≤ evidence.reported ∧
  ((259200 ≤ evidence.age ∧ 5 * evidence.mapped ≤ 4 * evidence.reported) ∨
    (86400 ≤ evidence.age ∧ 2 * evidence.mapped ≤ evidence.reported ∧
      2 ≤ evidence.confirmations))

instance (evidence : Evidence) : Decidable (Eligible evidence) := by
  unfold Eligible
  cases evidence.baseline <;>
  infer_instance

def takeover (evidence : Evidence) : Bool := decide (Eligible evidence)

theorem takeover_requires_subsequent_report (evidence : Evidence)
    (eligible : Eligible evidence) : evidence.reportNewer = true :=
  eligible.1

theorem takeover_requires_absolute_growth (evidence : Evidence)
    (eligible : Eligible evidence) : evidence.mapped + 10 ≤ evidence.reported :=
  eligible.2.2.1

theorem takeover_never_before_one_day (evidence : Evidence)
    (eligible : Eligible evidence) : 86400 ≤ evidence.age := by
  rcases eligible.2.2.2 with ordinary | rapid
  · omega
  · exact rapid.1

theorem early_takeover_requires_distinct_confirmations (evidence : Evidence)
    (eligible : Eligible evidence) (early : evidence.age < 259200) :
    2 ≤ evidence.confirmations := by
  rcases eligible.2.2.2 with ordinary | rapid
  · omega
  · exact rapid.2.2

theorem takeover_must_outgrow_survey_baseline (evidence : Evidence) (baseline : Nat)
    (known : evidence.baseline = some baseline) (eligible : Eligible evidence) :
    baseline < evidence.reported := by
  simpa [known] using eligible.2.1

theorem waiting_preserves_eligibility (evidence : Evidence) (later : Int)
    (elapsed : evidence.age ≤ later) (eligible : Eligible evidence) :
    Eligible { evidence with age := later } := by
  refine ⟨eligible.1, eligible.2.1, eligible.2.2.1, ?_⟩
  rcases eligible.2.2.2 with ordinary | rapid
  · exact Or.inl ⟨Int.le_trans ordinary.1 elapsed, ordinary.2⟩
  · exact Or.inr ⟨Int.le_trans rapid.1 elapsed, rapid.2⟩

/-- Large unconfirmed reversions cannot replace the most recently accepted report. -/
def acceptReport (previous current : Nat) (confirmed : Bool) : Bool :=
  confirmed || decide (¬ (5 * current < 4 * previous ∧ current + 10 ≤ previous))

theorem confirmed_corrections_are_accepted (previous current : Nat) :
    acceptReport previous current true = true := by
  simp [acceptReport]

theorem rejected_report_has_both_decrease_signals (previous current : Nat)
    (rejected : acceptReport previous current false = false) :
    5 * current < 4 * previous ∧ current + 10 ≤ previous := by
  simpa [acceptReport] using rejected

end PeriScribe.AreaPolicy
