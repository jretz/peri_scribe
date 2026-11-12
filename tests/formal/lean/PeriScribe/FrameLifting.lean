namespace PeriScribe.FrameLifting

variable {Field Value : Type}

abbrev Valuation (Field Value : Type) := Field → Value

def agrees (fields : Field → Bool) (first second : Valuation Field Value) : Prop :=
  ∀ field, fields field = true → first field = second field

def transfer (writes : Field → Bool) (before successor : Valuation Field Value) :
    Valuation Field Value :=
  fun field => if writes field then successor field else before field

theorem transfer_frame (writes : Field → Bool) (before successor : Valuation Field Value)
    (copied : agrees (fun field => !writes field) before successor) :
    transfer writes before successor = successor := by
  funext field
  cases h : writes field
  · have same := copied field (by simp [h])
    simp [transfer, h, same]
  · simp [transfer, h]

theorem transfer_erases_template_frame (writes : Field → Bool)
    (before first second : Valuation Field Value)
    (same : agrees writes first second) :
    transfer writes before first = transfer writes before second := by
  funext field
  cases h : writes field
  · simp [transfer, h]
  · simpa [transfer, h] using same field h

theorem transfer_map (writes : Field → Bool)
    (before : Valuation Field Value) (successors : List (Valuation Field Value))
    (copied : ∀ successor ∈ successors, agrees (fun field => !writes field) before successor) :
    successors.map (transfer writes before) = successors := by
  conv => rhs; rw [← List.map_id successors]
  apply List.map_congr_left
  intro successor member
  exact transfer_frame writes before successor (copied successor member)

structure Certificate (action : Valuation Field Value → List (Valuation Field Value))
    (reads writes : Field → Bool) where
  frame : ∀ before successor, successor ∈ action before →
    agrees (fun field => !writes field) before successor
  orderedWrites : ∀ a b, agrees reads a b →
    ∀ before, (action a).map (transfer writes before) =
      (action b).map (transfer writes before)

theorem exact_successors
    {action : Valuation Field Value → List (Valuation Field Value)}
    {reads writes : Field → Bool} (certificate : Certificate action reads writes)
    (representative current : Valuation Field Value)
    (sameReads : agrees reads representative current) :
    (action representative).map (transfer writes current) = action current := by
  calc
    (action representative).map (transfer writes current) =
        (action current).map (transfer writes current) :=
      certificate.orderedWrites representative current sameReads current
    _ = action current := transfer_map writes current (action current) (certificate.frame current)

def union (first second : Field → Bool) : Field → Bool :=
  fun field => first field || second field

def difference (first second : Field → Bool) : Field → Bool :=
  fun field => first field && !second field

theorem transfer_wider (writes extra : Field → Bool)
    (template current successor : Valuation Field Value)
    (same : agrees (difference extra writes) template current)
    (copied : agrees (fun field => !writes field) template successor) :
    transfer (union writes extra) current successor = transfer writes current successor := by
  funext field
  cases h : writes field
  · cases e : extra field
    · simp [transfer, union, h, e]
    · have before := same field (by simp [difference, h, e])
      have after := copied field (by simp [h])
      simpa [transfer, union, h, e] using after.symm.trans before
  · simp [transfer, union, h]

theorem widen_certificate
    {action : Valuation Field Value → List (Valuation Field Value)}
    {reads writes : Field → Bool} (certificate : Certificate action reads writes)
    (extra : Field → Bool) :
    Certificate action (union reads (difference extra writes)) (union writes extra) := by
  constructor
  · intro before successor member field stable
    exact certificate.frame before successor member field (by
      cases h : writes field
      · simp [h]
      · simp [union, h] at stable)
  · intro a b agreement before
    have sharedReads : agrees reads a b := fun field read =>
      agreement field (by simp [union, read])
    have sharedWidening : agrees (difference extra writes) a b := fun field read =>
      agreement field (by simp [union, read])
    have transferFrom :
        ∀ successor ∈ action a, ∀ second ∈ action b,
          agrees writes successor second →
          agrees (union writes extra) successor second := by
      intro successor firstMember second secondMember same field selected
      cases h : writes field
      · have e : extra field = true := by simpa [union, h] using selected
        have input := sharedWidening field (by simp [difference, h, e])
        have firstCopy := certificate.frame a successor firstMember field (by simp [h])
        have secondCopy := certificate.frame b second secondMember field (by simp [h])
        exact firstCopy.symm.trans (input.trans secondCopy)
      · exact same field h
    have ordered := certificate.orderedWrites a b sharedReads before
    generalize ha : action a = first at ordered ⊢
    generalize hb : action b = second at ordered ⊢
    rw [ha, hb] at transferFrom
    clear ha hb
    induction first generalizing second with
    | nil => cases second <;> simp_all
    | cons head tail induction =>
      cases second with
      | nil => simp at ordered
      | cons next rest =>
        simp only [List.map_cons, List.cons.injEq] at ordered ⊢
        constructor
        · apply transfer_erases_template_frame
          apply transferFrom head (by simp) next (by simp)
          intro field written
          have equal := congrFun ordered.1 field
          simpa [transfer, written] using equal
        · apply induction rest
          · intro successor firstMember second secondMember
            exact transferFrom successor (by simp [firstMember]) second (by simp [secondMember])
          · exact ordered.2

inductive Reached (next : Valuation Field Value → List (Valuation Field Value))
    (initial : Valuation Field Value → Prop) : Valuation Field Value → Prop
  | initial {state} : initial state → Reached next initial state
  | next {state successor} :
      Reached next initial state → successor ∈ next state → Reached next initial successor

theorem same_reachability
    {next lifted : Valuation Field Value → List (Valuation Field Value)}
    {initial : Valuation Field Value → Prop} {state : Valuation Field Value}
    (same : ∀ current, lifted current = next current) :
    Reached lifted initial state ↔ Reached next initial state := by
  constructor
  · intro reached
    induction reached with
    | initial initial => exact Reached.initial initial
    | next _ edge induction => exact Reached.next induction (by simpa [same] using edge)
  · intro reached
    induction reached with
    | initial initial => exact Reached.initial initial
    | next _ edge induction => exact Reached.next induction (by simpa [same] using edge)


end PeriScribe.FrameLifting
