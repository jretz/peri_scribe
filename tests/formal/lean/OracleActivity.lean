import PeriScribe.FireActivity

namespace PeriScribe.ActivityOracle

def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => pure value
  | none => .error s!"Expected signed elapsed seconds: {text}"

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => .error s!"Expected exact nonnegative acres: {text}"

def observation (text : String) : Except String FireActivity.Observation := do
  match text.splitOn "," with
  | [time, area] => return ⟨← integer time, ← natural area⟩
  | _ => throw "Expected time,area"

def observations (text : String) : Except String (List FireActivity.Observation) :=
  (text.trimAscii.toString.splitOn " " |>.filter (· != "")).mapM observation

def statusCode : FireActivity.Status → Nat
  | .inactive => 0
  | .active => 1
  | .holding => 2

def windowText (value : Option (Nat × Nat)) : String :=
  match value with
  | none => "-1 -1"
  | some (baseline, growth) => s!"{baseline} {growth}"

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | [header, reported, mapped] =>
    match header.trimAscii.toString.splitOn " " with
    | ["status", source, reference] =>
      if source != "0" && source != "1" then throw "Expected source activity 0 or 1"
      return toString (statusCode (FireActivity.status (source == "1")
        (← integer reference) (← observations reported) (← observations mapped)))
    | _ => throw "Expected status sourceActive reference"
  | [header, rows] =>
    match header.trimAscii.toString.splitOn " " with
    | ["window", reference, width] =>
      return windowText (FireActivity.window (← integer reference) (← integer width)
        (← observations rows))
    | _ => throw "Expected window reference width"
  | _ => throw "Unexpected activity request sections"

end PeriScribe.ActivityOracle

/-- Evaluate the proved exact history policy over independent batched requests. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.ActivityOracle.respond line.trimAscii.toString with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
