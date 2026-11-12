import PeriScribe.EffectRefinement

namespace PeriScribe.PipelineFileFootprint

open PeriScribe.EffectRefinement

structure Entry where
  bytes : List UInt8
  stamp : Option Nat
  deriving Repr, DecidableEq

inductive Command where
  | replace (bytes : List UInt8)
  | write (bytes : List UInt8)
  | publish (bytes : List UInt8) (stamp : Nat)
  | touch
  | remove (missingOk : Bool)
  deriving Repr, DecidableEq

inductive ErrorKind where
  | os
  | processLoss
  deriving Repr, DecidableEq

inductive Boundary where
  | complete
  | before (error : ErrorKind)
  | after (error : ErrorKind)
  | stagingBefore (error : ErrorKind)
  | stagingAfter (error : ErrorKind)
  deriving Repr, DecidableEq

inductive Reply where
  | done
  | interrupted (error : ErrorKind)
  | missing
  | unsupported
  deriving Repr, DecidableEq

inductive Primitive where
  | writeStage (bytes : List UInt8)
  | replaceTarget
  | writeTarget (bytes : List UInt8)
  | stampTarget (stamp : Nat)
  | touchTarget
  | unlinkTarget (missingOk : Bool)
  deriving Repr, DecidableEq


/-- Capability order exposed by the certified source. -/
def program : Command → List Primitive
  | .replace bytes => [.writeStage bytes, .replaceTarget]
  | .touch => [.touchTarget]
  | .remove missingOk => [.unlinkTarget missingOk]
  | .write bytes => [.writeTarget bytes]
  | .publish bytes stamp => [.writeTarget bytes, .stampTarget stamp]


def calls (command : Command) (boundary : Boundary) : List Primitive :=
  match command, boundary with
  | .replace bytes, .stagingBefore _
  | .replace bytes, .stagingAfter _ => [.writeStage bytes]
  | .replace bytes, _ => [.writeStage bytes, .replaceTarget]
  | .publish bytes _, .before _ => [.writeTarget bytes]
  | .publish bytes stamp, _ => [.writeTarget bytes, .stampTarget stamp]
  | .write bytes, _ => [.writeTarget bytes]
  | .touch, _ => [.touchTarget]
  | .remove missingOk, _ => [.unlinkTarget missingOk]

def stageSupported (command : Command) : Bool :=
  match command with
  | .replace _ => true
  | _ => false

def emptyEntry : Entry := ⟨[], none⟩

structure Outcome where
  target : Option Entry
  reply : Reply
  trace : List Primitive
  deriving Repr, DecidableEq

structure Storage where
  target : Option Entry
  stage : Option Entry
  deriving Repr, DecidableEq

/-- State transitions for one primitive against actual previous contents. -/
def runPrimitive (state : Storage) : Primitive → Storage × Reply
  | .writeStage bytes => ({state with stage := some ⟨bytes, none⟩}, .done)
  | .replaceTarget => (⟨state.stage, none⟩, .done)
  | .writeTarget bytes => ({state with target := some ⟨bytes, none⟩}, .done)
  | .stampTarget stamp =>
      match state.target with
      | some entry => ({state with target := some {entry with stamp := some stamp}}, .done)
      | none => (state, .missing)
  | .touchTarget =>
      match state.target with
      | some _ => (state, .done)
      | none => ({state with target := some emptyEntry}, .done)
  | .unlinkTarget missingOk =>
      match state.target, missingOk with
      | none, false => (state, .missing)
      | _, _ => ({state with target := none}, .done)

structure Injection where
  index : Nat
  after : Bool
  error : ErrorKind

def injection (command : Command) (boundary : Boundary) : Option Injection :=
  match boundary with
  | .complete => none
  | .before error =>
      match command with
      | .replace _ => some ⟨1, false, error⟩
      | _ => some ⟨0, false, error⟩
  | .after error =>
      match command with
      | .replace _ | .publish _ _ => some ⟨1, true, error⟩
      | _ => some ⟨0, true, error⟩
  | .stagingBefore error => some ⟨0, false, error⟩
  | .stagingAfter error => some ⟨0, true, error⟩

def interruptAt (fault : Option Injection) (position : Nat) : Option Injection :=
  match fault with
  | some selected => if selected.index = position then fault else none
  | none => none

structure Run where
  state : Storage
  reply : Reply
  trace : List Primitive

def Run.prepend (primitive : Primitive) (run : Run) : Run :=
  {run with trace := primitive :: run.trace}

/-- Record attempts, interrupt at the selected boundary and preserve ordinary errors. -/
def runProgram (fault : Option Injection) (position : Nat) (state : Storage) :
    List Primitive → Run
  | [] => ⟨state, .done, []⟩
  | primitive :: rest =>
      let run : Run :=
        match interruptAt fault position with
        | some selected =>
            if selected.after then
              let (next, reply) := runPrimitive state primitive
              ⟨next, if reply == Reply.done then .interrupted selected.error else reply, []⟩
            else
              ⟨state, .interrupted selected.error, []⟩
        | none =>
            let (next, reply) := runPrimitive state primitive
            if reply == Reply.done then runProgram fault (position + 1) next rest
            else ⟨next, reply, []⟩
      run.prepend primitive

def stagingBoundary : Boundary → Bool
  | .stagingBefore _ | .stagingAfter _ => true
  | _ => false

/-- TemporaryDirectory discards its private contents on success and either modeled exception. -/
def execute (command : Command) (old : Option Entry) (boundary : Boundary) : Run :=
  if stagingBoundary boundary && !stageSupported command then
    ⟨⟨old, none⟩, .unsupported, []⟩
  else
    let run := runProgram (injection command boundary) 0 ⟨old, none⟩ (program command)
    {run with state := {run.state with stage := none}}

def concrete (command : Command) (old : Option Entry) (boundary : Boundary) : Outcome :=
  let run := execute command old boundary
  ⟨run.state.target, run.reply, run.trace⟩

theorem cleansPrivateStage (command : Command) (old : Option Entry) (boundary : Boundary) :
    (execute command old boundary).state.stage = none := by
  unfold execute
  split <;> rfl

inductive Change where
  | retain
  | createEmpty
  | installArgument
  | remove
  deriving Repr, DecidableEq

def Change.apply (change : Change) (command : Command) (old : Option Entry) : Option Entry :=
  match change with
  | .retain => old
  | .createEmpty => some emptyEntry
  | .installArgument =>
      match command with
      | .replace bytes | .write bytes => some ⟨bytes, none⟩
      | .publish bytes stamp => some ⟨bytes, some stamp⟩
      | _ => none
  | .remove => none

structure Recipe where
  change : Change
  reply : Reply
  trace : List Primitive
  deriving Repr, DecidableEq

/-- Independent interface algebra. The old bytes are unavailable to this reducer. -/
def completeRecipe (command : Command) (present : Bool) : Change × Reply :=
  match command, present with
  | .replace _, _ | .write _, _ | .publish _ _, _ => (.installArgument, .done)
  | .touch, false => (.createEmpty, .done)
  | .touch, true => (.retain, .done)
  | .remove false, false => (.retain, .missing)
  | .remove _, _ => (.remove, .done)

def recipe (command : Command) (present : Bool) (boundary : Boundary) : Recipe :=
  let trace := calls command boundary
  match boundary with
  | .complete =>
      let (change, reply) := completeRecipe command present
      ⟨change, reply, trace⟩
  | .before error => ⟨.retain, .interrupted error, trace⟩
  | .after error =>
      let (change, reply) := completeRecipe command present
      ⟨change, if reply == Reply.done then .interrupted error else reply, trace⟩
  | .stagingBefore error | .stagingAfter error =>
      if stageSupported command then ⟨.retain, .interrupted error, trace⟩
      else ⟨.retain, .unsupported, []⟩

def Recipe.lift (plan : Recipe) (command : Command) (old : Option Entry) : Outcome :=
  ⟨plan.change.apply command old, plan.reply, plan.trace⟩

theorem targetQuotient (command : Command) (old : Option Entry) (boundary : Boundary) :
    concrete command old boundary = (recipe command old.isSome boundary).lift command old := by
  cases command
  case remove missingOk =>
    cases missingOk <;> cases old <;> cases boundary <;> rfl
  all_goals
    cases old <;> cases boundary <;> rfl

def patch {Key : Type} [DecidableEq Key] (frame : Key → Option Entry)
    (target : Key) (replacement : Option Entry) : Key → Option Entry :=
  fun key => if key = target then replacement else frame key

structure FrameOutcome (Key : Type) where
  frame : Key → Option Entry
  reply : Reply
  trace : List Primitive

def runConcrete {Key : Type} [DecidableEq Key] (frame : Key → Option Entry)
    (target : Key) (command : Command) (boundary : Boundary) : FrameOutcome Key :=
  let output := concrete command (frame target) boundary
  ⟨patch frame target output.target, output.reply, output.trace⟩

def liftFrame {Key : Type} [DecidableEq Key] (frame : Key → Option Entry)
    (target : Key) (command : Command) (plan : Recipe) : FrameOutcome Key :=
  let output := plan.lift command (frame target)
  ⟨patch frame target output.target, output.reply, output.trace⟩

theorem frameQuotient {Key : Type} [DecidableEq Key] (frame : Key → Option Entry)
    (target : Key) (command : Command) (boundary : Boundary) :
    runConcrete frame target command boundary =
      liftFrame frame target command (recipe command (frame target).isSome boundary) := by
  simp only [runConcrete, liftFrame]
  rw [targetQuotient]

theorem untouchedSibling {Key : Type} [DecidableEq Key] (frame : Key → Option Entry)
    (target sibling : Key) (command : Command) (boundary : Boundary)
    (different : sibling ≠ target) :
    (runConcrete frame target command boundary).frame sibling = frame sibling := by
  simp [runConcrete, patch, different]

theorem sameInterfaceSameReplyAndCalls (command : Command) (boundary : Boundary)
    (old other : Option Entry) (present : old.isSome = other.isSome) :
    (concrete command old boundary).reply = (concrete command other boundary).reply ∧
    (concrete command old boundary).trace = (concrete command other boundary).trace := by
  rw [targetQuotient command old boundary, targetQuotient command other boundary, present]
  exact ⟨rfl, rfl⟩

/-- A separately checked target-only reader composes with any surrounding frame. -/
theorem readerFrame {Key Reply : Type} (read : Option Entry → Reply)
    (left right : Key → Option Entry) (target : Key) (sameTarget : left target = right target) :
    read (left target) = read (right target) := congrArg read sameTarget

structure Invocation (Key : Type) where
  target : Key
  command : Command
  boundary : Boundary

def actualStep {Key : Type} [DecidableEq Key] (frame : Key → Option Entry)
    (call : Invocation Key) : EffectResult (Key → Option Entry) Reply Primitive :=
  let output := runConcrete frame call.target call.command call.boundary
  ⟨output.frame, output.reply, output.trace⟩

def factoredStep {Key : Type} [DecidableEq Key] (frame : Key → Option Entry)
    (call : Invocation Key) : EffectResult (Key → Option Entry) Reply Primitive :=
  let output := liftFrame frame call.target call.command
    (recipe call.command (frame call.target).isSome call.boundary)
  ⟨output.frame, output.reply, output.trace⟩

theorem sameStep {Key : Type} [DecidableEq Key] (frame : Key → Option Entry)
    (call : Invocation Key) : actualStep frame call = factoredStep frame call := by
  simp only [actualStep, factoredStep]
  rw [frameQuotient]

/-- Equal raw replies keep the same continuations and exact ordered traces. -/
theorem composedReplay {Key Result : Type} [DecidableEq Key] (fuel : Nat)
    (program : Program (Invocation Key) Reply Result) (frame : Key → Option Entry) :
    (run actualStep fuel program frame).state = (run factoredStep fuel program frame).state ∧
    (run actualStep fuel program frame).result = (run factoredStep fuel program frame).result ∧
    (run actualStep fuel program frame).events = (run factoredStep fuel program frame).events := by
  apply runRefines actualStep factoredStep Eq _ fuel program frame frame rfl
  intro left right call same
  subst right
  rw [sameStep]
  exact ⟨rfl, rfl, rfl⟩

theorem keepsUntouchedSiblings {Key Result : Type} [DecidableEq Key] (fuel : Nat)
    (program : Program (Invocation Key) Reply Result) (frame : Key → Option Entry) (sibling : Key)
    (outside : ∀ event ∈ (run actualStep fuel program frame).events,
      sibling ≠ event.command.target) :
    (run actualStep fuel program frame).state sibling = frame sibling := by
  apply preservesOutsideTrace actualStep id (fun call key => key = call.target) _
    fuel program frame sibling outside
  intro state call key untouched
  exact untouchedSibling state call.target key call.command call.boundary untouched

abbrev Frame (Key : Type) := Key → Option Entry

inductive ReadKind where
  | bytes
  | exists
  | stamp
  | identity

inductive Answer (Key : Type) where
  | bytes (value : List UInt8)
  | exists (value : Bool)
  | stamp (value : Nat)
  | identity (size stamp : Nat)
  | missing (target : Key)
  | invalidStamp
  | write (value : Reply)
  | observed (frame : Frame Key)
  | interrupted (boundary : Nat) (frame : Frame Key)

inductive Request (Key : Type) where
  | read (target : Key) (kind : ReadKind)
  | write (call : Invocation Key)
  | observe
  | interrupt (boundary : Nat)

def readFrame {Key : Type} (frame : Frame Key) (target : Key) (kind : ReadKind) : Answer Key :=
  match kind, frame target with
  | .exists, entry => .exists entry.isSome
  | _, none => .missing target
  | .bytes, some entry => .bytes entry.bytes
  | .stamp, some ⟨_, some stamp⟩ => .stamp stamp
  | .identity, some ⟨bytes, some stamp⟩ => .identity bytes.length stamp
  | _, some _ => .invalidStamp

def mixedStep {Key : Type}
    (writeStep : Frame Key → Invocation Key → EffectResult (Frame Key) Reply Primitive)
    (readStep : Frame Key → Key → ReadKind → Answer Key)
    (frame : Frame Key) (request : Request Key) : EffectResult (Frame Key) (Answer Key) Primitive :=
  match request with
  | .read target kind => ⟨frame, readStep frame target kind, []⟩
  | .write call =>
      let result := writeStep frame call
      ⟨result.state, .write result.reply, result.observations⟩
  | .observe => ⟨frame, .observed frame, []⟩
  | .interrupt boundary => ⟨frame, .interrupted boundary frame, []⟩

/-- The scoped reader and frame-preserving callbacks keep the original reply order. -/
theorem orderedReadsAndWrites {Key Result : Type} [DecidableEq Key]
    (nativeRead : Frame Key → Key → ReadKind → Answer Key)
    (readerBinding : ∀ frame target kind,
      nativeRead frame target kind = readFrame frame target kind)
    (fuel : Nat) (program : Program (Request Key) (Answer Key) Result) (frame : Frame Key) :
    (run (mixedStep actualStep nativeRead) fuel program frame).state =
      (run (mixedStep factoredStep readFrame) fuel program frame).state ∧
    (run (mixedStep actualStep nativeRead) fuel program frame).result =
      (run (mixedStep factoredStep readFrame) fuel program frame).result ∧
    (run (mixedStep actualStep nativeRead) fuel program frame).events =
      (run (mixedStep factoredStep readFrame) fuel program frame).events := by
  apply runRefines (mixedStep actualStep nativeRead) (mixedStep factoredStep readFrame)
    Eq _ fuel program frame frame rfl
  intro left right command same
  subst right
  cases command with
  | read target kind => simp [mixedStep, readerBinding]
  | write call => simp [mixedStep, sameStep]
  | observe => exact ⟨rfl, rfl, rfl⟩
  | interrupt boundary => exact ⟨rfl, rfl, rfl⟩

/-- The primitive arguments remain symbolic in the schedule sent across the oracle. -/
def Primitive.code : Primitive → Nat
  | .writeStage _ => 1
  | .replaceTarget => 2
  | .writeTarget _ => 3
  | .stampTarget _ => 4
  | .touchTarget => 5
  | .unlinkTarget _ => 6

def Change.code : Change → Nat
  | .retain => 0
  | .createEmpty => 1
  | .installArgument => 2
  | .remove => 3

/-- Length delimiters separate the command trace from its four fault positions. -/
def schedule (command : Command) : List Nat :=
  let steps := program command
  let position boundary := (injection command boundary).map (fun fault => fault.index + 1)
  let staging boundary := if stageSupported command then (position boundary).getD 0 else 0
  [steps.length] ++ steps.map Primitive.code ++
    [(position (.before .os)).getD 0, (position (.after .os)).getD 0,
      staging (.stagingBefore .os), staging (.stagingAfter .os)]

def scheduleCommands : List Command := [.replace [], .touch, .remove true, .write [], .publish [] 0]

def programShape : List Nat := scheduleCommands.flatMap schedule

def acceptsProgram (shape : List Nat) : Bool := shape == programShape

theorem acceptsExactProgram (shape : List Nat) : acceptsProgram shape = true ↔ shape = programShape := by
  simp [acceptsProgram]

/-- Return the symbolic transfer for absent and present targets in each command class. -/
def changes : List Nat :=
  scheduleCommands.flatMap fun command => [false, true].map fun present =>
    (completeRecipe command present).1.code

end PeriScribe.PipelineFileFootprint
