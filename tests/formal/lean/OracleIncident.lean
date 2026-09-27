import PeriScribe.IncidentHistory

namespace PeriScribe.IncidentOracle

/-- Invalid input must fail explicitly rather than reduce the checked case domain. -/
def natural (value : String) : Except String Nat :=
  match value.toNat? with
  | some result => pure result
  | none => throw s!"Expected natural number: {value}"

def optional (value : String) : Except String (Option Nat) :=
  if value = "-1" then pure none else some <$> natural value

def boolean (value : String) : Except String Bool :=
  if value = "0" then pure false else if value = "1" then pure true
  else throw "Expected Boolean"

def entry (text : String) : Except String IncidentHistory.Entry := do
  match text.splitOn "," with
  | [time, direct, serial, file, report, confirmed, field, value] =>
    return ⟨← natural time, ← boolean direct, ← natural serial, ← natural file,
      ← optional report, ← boolean confirmed, ← natural field, ← natural value⟩
  | _ => throw "Expected incident field vector"

def encode (item : IncidentHistory.Entry) : List Int :=
  [item.time, if item.direct then 1 else 0, item.serial, item.file,
    (item.report.map Int.ofNat).getD (-1), if item.confirmed then 1 else 0,
    item.field, item.value]

def respond (words : List String) : Except String String := do
  match words with
  | "history" :: entries =>
    let results := IncidentHistory.reconcile (← entries.mapM entry)
    return String.intercalate " " ((results.flatMap encode).map toString)
  | _ => throw "Expected history followed by incident fields"

end PeriScribe.IncidentOracle

/-- One process checks batches of complete multi-field histories. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    let words := (line.trimAscii.toString.splitOn " ").filter (· != "")
    match PeriScribe.IncidentOracle.respond words with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
