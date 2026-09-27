import PeriScribe.RawDecoding

namespace PeriScribe.RawDecodingOracle

def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => pure value
  | none => throw s!"Invalid integer: {text}"

def candidate (text : String) : Except String (RawDecoding.Candidate Int) := do
  match text.splitOn ":" with
  | ["missing"] => return .missing
  | ["boolean"] => return .boolean true
  | ["malformed"] => return .malformed
  | ["nonfinite"] => return .nonfinite
  | ["value", value] => return .usable (← integer value)
  | _ => throw s!"Invalid candidate: {text}"

def instant (text : String) : Except String (Option Int) := do
  match text.splitOn ":" with
  | ["invalid"] => return none
  | ["wall", wall, offset] =>
    return RawDecoding.normalize (← integer wall) (← integer offset)
  | ["milliseconds", value] => return RawDecoding.milliseconds (← integer value)
  | _ => throw s!"Invalid instant: {text}"

def render : Option Int → String
  | none => "0"
  | some value => s!"1 {value}"

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | ["fields", values] =>
    let parsed ← (values.splitOn " " |>.filter (· != "")).mapM candidate
    return render (RawDecoding.first RawDecoding.decode parsed)
  | ["times", values] =>
    let parsed ← (values.splitOn " " |>.filter (· != "")).mapM instant
    return render (RawDecoding.first id parsed)
  | _ => throw "Expected fields|candidates or times|instants"

end PeriScribe.RawDecodingOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.RawDecodingOracle.respond line.trimAscii.toString with
    | .ok result => output.putStrLn result
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
