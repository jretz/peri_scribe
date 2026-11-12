import Std

namespace PeriScribe.EffectRefinement

inductive Program (Command Reply Result : Type) : Type where
  | halt (result : Result)
  | perform (command : Command) (next : Reply → Program Command Reply Result)

structure EffectResult (State Reply Observation : Type) where
  state : State
  reply : Reply
  observations : List Observation

structure Event (Command Reply Observation : Type) where
  command : Command
  reply : Reply
  observations : List Observation

structure Execution (State Command Reply Observation Result : Type) where
  state : State
  result : Option Result
  events : List (Event Command Reply Observation)

/-- Replies may be `Except Fault Value`; the program decides which failures recover. -/
def run {State Command Reply Observation Result : Type}
    (effect : State → Command → EffectResult State Reply Observation) :
    Nat → Program Command Reply Result → State → Execution State Command Reply Observation Result
  | _, .halt result, state => ⟨state, some result, []⟩
  | 0, .perform _ _, state => ⟨state, none, []⟩
  | fuel + 1, .perform command next, state =>
    let change := effect state command
    let following := run effect fuel (next change.reply) change.state
    ⟨following.state, following.result,
      ⟨command, change.reply, change.observations⟩ :: following.events⟩

/-- Each actual effect must preserve the relation and return the same reply and evidence.
    The continuation receives that reply, retaining all later effects and their order. -/
theorem runRefines {Physical Logical Command Reply Observation Result : Type}
    (actual : Physical → Command → EffectResult Physical Reply Observation)
    (model : Logical → Command → EffectResult Logical Reply Observation)
    (related : Physical → Logical → Prop)
    (oneStep : ∀ physical logical command, related physical logical →
      related (actual physical command).state (model logical command).state ∧
      (actual physical command).reply = (model logical command).reply ∧
      (actual physical command).observations = (model logical command).observations) :
    ∀ fuel (program : Program Command Reply Result) physical logical,
      related physical logical →
      related (run actual fuel program physical).state (run model fuel program logical).state ∧
      (run actual fuel program physical).result = (run model fuel program logical).result ∧
      (run actual fuel program physical).events = (run model fuel program logical).events := by
  intro fuel
  induction fuel with
  | zero =>
    intro program physical logical initial
    cases program <;> exact ⟨initial, rfl, rfl⟩
  | succ fuel previous =>
    intro program physical logical initial
    cases program with
    | halt result => exact ⟨initial, rfl, rfl⟩
    | perform command next =>
      obtain ⟨relatedAfter, sameReply, sameEvidence⟩ := oneStep physical logical command initial
      have rest := previous (next (actual physical command).reply)
        (actual physical command).state (model logical command).state relatedAfter
      simp only [run]
      rw [sameReply, sameEvidence] at *
      exact ⟨rest.1, rest.2.1, congrArg (List.cons
        ⟨command, (model logical command).reply, (model logical command).observations⟩) rest.2.2⟩

/-- A key outside every emitted command's footprint keeps its exact initial value. -/
theorem preservesOutsideTrace {State Command Reply Observation Result Key Value : Type}
    (effect : State → Command → EffectResult State Reply Observation)
    (value : State → Key → Value)
    (touches : Command → Key → Prop)
    (frame : ∀ state command key, ¬ touches command key →
      value (effect state command).state key = value state key) :
    ∀ fuel (program : Program Command Reply Result) state key,
      (∀ event ∈ (run effect fuel program state).events, ¬ touches event.command key) →
      value (run effect fuel program state).state key = value state key := by
  intro fuel
  induction fuel with
  | zero => intro program state key outside; cases program <;> rfl
  | succ fuel previous =>
    intro program state key outside
    cases program with
    | halt result => rfl
    | perform command next =>
      simp only [run] at *
      exact (previous (next (effect state command).reply) (effect state command).state key
        (fun event member => outside event (List.mem_cons_of_mem _ member))).trans
        (frame state command key (outside _ List.mem_cons_self))

end PeriScribe.EffectRefinement
