import PeriScribe.RankedViews
import PeriScribe.OutputReferences

namespace PeriScribe.OutputsOracle

def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => pure value
  | none => .error s!"Invalid integer: {text}"

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => .error s!"Invalid natural: {text}"

def values (text : String) : List String :=
  text.trimAscii.toString.splitOn " " |>.filter (· != "")

def fire (text : String) : Except String RankedViews.Fire := do
  match text.splitOn "," with
  | owner :: name :: identifiers =>
    return ⟨← natural owner, ← natural name, ← identifiers.mapM natural⟩
  | _ => throw "Expected owner,name,identifiers"

def score (text : String) : Except String RankedViews.Score := do
  match text.splitOn "," with
  | [identifier, name, value, serial] =>
    return ⟨← if identifier = "n" then pure none else some <$> natural identifier,
      ← natural name, ← integer value, ← natural serial⟩
  | _ => throw "Expected identifier,name,value,serial"

def measurement (text : String) : Except String RankedViews.Measurement := do
  match text.splitOn "," with
  | [time, area] => return ⟨← integer time, ← integer area⟩
  | _ => throw "Expected time,area"

def resource (text : String) : Except String OutputReferences.Resource := do
  match text.splitOn "," with
  | [name, owner] => return ⟨← natural name, ← natural owner⟩
  | _ => throw "Expected resource,owner"

def numbers (items : List Nat) : String :=
  String.intercalate " " (items.map toString)

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | [header, first, second] =>
    match values header with
    | ["top", limit] =>
      let fires ← (values first).mapM fire
      let scores ← (values second).mapM score
      return numbers (RankedViews.top (← natural limit) fires scores)
    | ["associations"] =>
      let fires ← (values first).mapM fire
      let scores ← (values second).mapM score
      let associated := RankedViews.associations fires scores
      return String.intercalate " " (associated.flatMap fun (owner, score) =>
        [toString owner, toString score.value, toString score.serial])
    | ["allocate"] =>
      let used ← (values first).mapM natural
      let candidates ← (values second).mapM natural
      return toString ((OutputReferences.allocate used candidates).getD 999999)
    | ["closed"] =>
      let resources ← (values first).mapM resource
      let references ← (values second).mapM resource
      return if OutputReferences.closed resources references then "1" else "0"
    | _ => throw "Invalid three-section request"
  | [header, rows] =>
    match values header with
    | ["growth", now, width] =>
      let result := RankedViews.growth (← integer now) (← integer width)
        (← (values rows).mapM measurement)
      return match result with
      | none => "-99999999 -99999999 0 0"
      | some (growth, baseline) => s!"{growth} {baseline} " ++
        (if 1000 ≤ growth then "1 " else "0 ") ++
        (if RankedViews.percentEligible growth baseline 10 then "1" else "0")
    | ["rings", folder] =>
      let targets := OutputReferences.ringTargets (← natural folder)
        (← natural rows.trimAscii.toString)
      return numbers (targets.flatMap fun (folder, index) => [folder, index])
    | ["reveal", step] =>
      let step ← natural step
      let count ← natural rows.trimAscii.toString
      return numbers ((List.range count).map fun index =>
        if OutputReferences.visibleThrough step index then 1 else 0)
    | ["window", now, width] =>
      let now ← integer now
      let width ← integer width
      let times ← (values rows).mapM integer
      return numbers (times.map fun time =>
        if RankedViews.inWindow now width time then 1 else 0)
    | _ => throw "Invalid two-section request"
  | _ => throw "Invalid output oracle request"

end PeriScribe.OutputsOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.OutputsOracle.respond line.trimAscii.toString with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
