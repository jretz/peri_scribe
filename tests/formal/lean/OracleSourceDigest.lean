import PeriScribe.SourceDigest

open PeriScribe.SourceDigest

def numbers (text : String) : Except String (List Nat) :=
  (text.splitOn " " |>.filter (· != "")).mapM fun value =>
    match value.toNat? with
    | some number => pure number
    | none => .error s!"Expected natural number: {value}"

def respond (line : String) : Except String (List Nat) := do
  match line.splitOn "|" with
  | "fields" :: parts => return fields (← parts.mapM numbers)
  | ["rows", values] => return orderedRows (← numbers values)
  | ["equal", schemaOne, rowsOne, schemaTwo, rowsTwo] =>
    let first := content (← numbers schemaOne) (← numbers rowsOne)
    let second := content (← numbers schemaTwo) (← numbers rowsTwo)
    return [if first = second then 1 else 0]
  | _ => throw "Expected fields, rows, or equal request"

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
