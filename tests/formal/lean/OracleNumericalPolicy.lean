import PeriScribe.NumericalPolicy
import PeriScribe.Scoring

open PeriScribe.NumericalPolicy

def numbers (text : String) : Except String (List Int) :=
  (text.splitOn " " |>.filter (· != "")).mapM fun value =>
    match value.toInt? with
    | some number => pure number
    | none => .error s!"Expected integer: {value}"

def bit (value : Bool) : Int := if value then 1 else 0

def tiers : List Int → Except String (List PeriScribe.Scoring.Tier)
  | [] => pure []
  | threshold :: points :: rest =>
    return (threshold.toNat, points.toNat) :: (← tiers rest)
  | _ => .error "Expected threshold/points pairs"

def respond (line : String) : Except String (List Int) := do
  match line.splitOn "|" with
  | ["arithmetic", arguments] =>
    match ← numbers arguments with
    | [left, right] => return [subtract left right, multiply left right,
        if right = 0 then 0 else divide left right]
    | _ => throw "Expected two finite operands"
  | ["publish", arguments] =>
    match ← numbers arguments with
    | [current, previous, threshold, conversion, tolerance] =>
      let change := subtract current previous
      let converted := multiply threshold conversion
      return [bit (publish change converted tolerance), change, converted]
    | _ => throw "Expected areas, threshold, conversion, and tolerance"
  | ["takeover", arguments] =>
    match ← numbers arguments with
    | [mapped, conversion, report, reportFactor, mappedFactor, baseline, minimum,
        significant, rapid, hasBaseline, newer, age, confirmations] =>
      return [bit (takeover mapped conversion report reportFactor mappedFactor baseline
        minimum significant rapid
        (hasBaseline != 0) (newer != 0) age confirmations.toNat)]
    | _ => throw "Expected area policy evidence"
  | ["accept", arguments] =>
    match ← numbers arguments with
    | [previous, current, minimum, significant, confirmed] =>
      return [bit (acceptReport previous current minimum significant (confirmed != 0))]
    | _ => throw "Expected previous/current area and policy"
  | ["tier", arguments] =>
    match ← numbers arguments with
    | value :: rest => return [PeriScribe.Scoring.tiered value.toNat (← tiers rest)]
    | _ => throw "Expected value and tiers"
  | _ => throw "Expected numerical policy operation"

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match respond line.trimAscii.toString with
    | .ok response => output.putStrLn (String.intercalate " " (response.map toString))
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
