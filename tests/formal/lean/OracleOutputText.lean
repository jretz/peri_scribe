import PeriScribe.OutputText

namespace PeriScribe.OutputTextOracle

def numbers (text : String) : Except String (List Nat) :=
  (text.splitOn " " |>.filter (· != "")).mapM fun token =>
    match token.toNat? with
    | some value => pure value
    | none => throw s!"Invalid codepoint: {token}"

def render (values : List Nat) : String :=
  String.intercalate " " (values.map toString)

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | [operation, input] =>
    let values ← numbers input
    match operation with
    | "normalize" => return render (OutputText.normalize values)
    | "markdown" =>
      return render ((OutputText.wire OutputText.markdownReserved values).toList.map
        Char.toNat)
    | "xml" =>
      return render ((OutputText.wire OutputText.xmlReserved values).toList.map Char.toNat)
    | "cdata" =>
      return render ((OutputText.cdataWire values).toList.map Char.toNat)
    | "rows" =>
      let pieces := values.flatMap fun count =>
        OutputText.row (List.replicate count [])
      return render (OutputText.syntaxTokens
        (OutputText.render OutputText.markdownReserved pieces))
    | _ => throw "Unknown text operation"
  | _ => throw "Expected operation|codepoints"

end PeriScribe.OutputTextOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.OutputTextOracle.respond line.trimAscii.toString with
    | .ok result => output.putStrLn result
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
