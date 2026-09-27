import PeriScribe.CacheDependencies

def numbers (text : String) : Except String (List Nat) :=
  (text.splitOn " " |>.filter (· != "")).mapM fun value =>
    match value.toNat? with
    | some number => pure number
    | none => .error s!"Expected natural number: {value}"

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | [required, keyed, first, second] =>
    let result := PeriScribe.CacheDependencies.check (← numbers required)
      (← numbers keyed) (← numbers first) (← numbers second)
    return String.intercalate " " (result.map toString)
  | _ => throw "Expected required fields, key fields, and two input vectors"

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match respond line.trimAscii.toString with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
