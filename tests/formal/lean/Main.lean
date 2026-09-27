import PeriScribe

namespace PeriScribe.Oracle

/-- Malformed vectors fail explicitly rather than quietly changing the tested domain. -/
def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => .ok value
  | none => .error s!"Expected a natural number: {text}"

/-- Signed elapsed time permits checkpoint dates later than the current clock. -/
def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => .ok value
  | none => .error s!"Expected an integer: {text}"

/-- Boolean fields reject ambiguous text at the conformance boundary. -/
def boolean (text : String) : Except String Bool :=
  match text with
  | "0" => .ok false
  | "1" => .ok true
  | _ => .error s!"Expected 0 or 1: {text}"

/-- Missing evidence has its own representation rather than sharing the value zero. -/
def optionalNatural (text : String) : Except String (Option Nat) :=
  if text = "-1" then .ok none else some <$> natural text

/-- The numeric transport order agrees with the pipeline prerequisite order. -/
def stage (text : String) : Except String Pipeline.Stage :=
  match text with
  | "0" => .ok .geography
  | "1" => .ok .score
  | "2" => .ok .kmz
  | "3" => .ok .reports
  | _ => .error s!"Expected derived stage 0..3: {text}"

/-- A small bitset transports all sixteen subsets without file-system state. -/
def stageBit : Pipeline.Stage → Nat
  | .geography => 1
  | .score => 2
  | .kmz => 4
  | .reports => 8

/-- Decoding restores the canonical order required by the durable state validator. -/
def pending (text : String) : Except String (List Pipeline.Stage) := do
  let mask ← natural text
  if mask ≥ 16 then throw "Expected pending mask 0..15"
  return Pipeline.stages.filter (fun stage => mask / stageBit stage % 2 == 1)

/-- One stable representation keeps output parsing independent of Lean formatting. -/
def bit (value : Bool) : String := if value then "1" else "0"

/-- Responses retain both unfinished work and its unconditional rebuild requirement. -/
def pendingText (state : Pipeline.Pending) : String :=
  let mask := state.remaining.foldl (fun value stage => value + stageBit stage) 0
  s!"{mask} {bit state.unconditional}"

/-- Codes preserve decision precedence for comparison with Python's named reasons. -/
def reasonCode : Pipeline.Reason → Nat
  | .noPublication => 0
  | .evacuations => 1
  | .sourceHistory => 2
  | .noChanges => 3
  | .area => 4
  | .timer => 5
  | .belowThreshold => 6

/-- Four separated cells exercise exact set membership without geometric tolerances. -/
def footprint (text : String) : Except String (Fin 4 → Bool) := do
  let mask ← natural text
  if mask ≥ 16 then throw "Expected footprint mask 0..15"
  return fun point => mask / (2 ^ point.val) % 2 == 1

/-- Every finite-cell output is represented in the same four-bit input basis. -/
def footprintText (shape : Fin 4 → Bool) : String :=
  toString ((if shape 0 then 1 else 0) + (if shape 1 then 2 else 0) +
    (if shape 2 then 4 else 0) + (if shape 3 then 8 else 0) : Nat)

/-- Requests execute the definitions imported by the checked theorem modules. -/
def respond (words : List String) : Except String String := do
  match words with
  | "corrected" :: masks =>
    let history ← masks.mapM footprint
    return String.intercalate " "
      ((Geography.booleanCorrected history).map footprintText)
  | ["complete", mask, force, completed] =>
    let state := Pipeline.Pending.mk (← pending mask) (← boolean force)
    return pendingText (Pipeline.complete state (← stage completed))
  | ["require", mask, force, requested, newForce] =>
    let state := Pipeline.Pending.mk (← pending mask) (← boolean force)
    return pendingText
      (Pipeline.require state (← pending requested) (← boolean newForce))
  | ["gate", valid, evacuations, history, hasPending, mapping, timer] =>
    let decision := Pipeline.gate (← boolean valid) (← boolean evacuations)
      (← boolean history) (← boolean hasPending) (← boolean mapping) (← boolean timer)
    return s!"{bit decision.proceed} {reasonCode decision.reason}"
  | ["takeover", mapped, reported, newer, baseline, age, confirmations] =>
    let evidence := AreaPolicy.Evidence.mk (← natural mapped) (← natural reported)
      (← boolean newer) (← optionalNatural baseline) (← integer age)
      (← natural confirmations)
    return bit (AreaPolicy.takeover evidence)
  | ["accept", previous, current, confirmed] =>
    let prior ← optionalNatural previous
    let value ← natural current
    let formal ← boolean confirmed
    return bit (match prior with
      | none => true
      | some old => AreaPolicy.acceptReport old value formal)
  | ["score", size, growth, first, buildings, evacuation, importance] =>
    let points ← natural importance
    if points > 3 then throw "Expected importance points 0..3"
    return toString (Scoring.total (← natural size) (← natural growth)
      (← natural first) (← natural buildings) (← boolean evacuation) points)
  | ["due", interval, hasPrevious, elapsed] =>
    let intervalSeconds ← natural interval
    let hasCheckpoint ← boolean hasPrevious
    let age ← integer elapsed
    return bit
      (Scheduling.due intervalSeconds (if hasCheckpoint then some age else none))
  | ["winner", previousValue, previousSource, previousTime,
      currentValue, currentSource, currentTime] =>
    let previous := Reconciliation.Measurement.mk (← natural previousValue)
      (← natural previousSource) (← optionalNatural previousTime)
    let current := Reconciliation.Measurement.mk (← natural currentValue)
      (← natural currentSource) (← optionalNatural currentTime)
    let selected := Reconciliation.winner previous current
    let time := selected.confirmedAt.map toString |>.getD "-1"
    return s!"{selected.value} {selected.provenance} {time}"
  | ["preserve", previous, current, confirmed, stale, area] =>
    return toString (Reconciliation.preserveConfirmed (← natural previous)
      (← natural current) (← boolean confirmed) (← boolean stale) (← boolean area))
  | _ => throw s!"Unknown request or wrong argument count: {words}"

end PeriScribe.Oracle

/-- Batched requests keep conformance checks independent of process startup cost. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    let words := line.trimAscii.toString.splitOn " "
    match PeriScribe.Oracle.respond words with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
