import PeriScribe.PayloadCodec

open PeriScribe.PayloadCodec

def respond (line : String) : Except String String := do
  let numbers ← (line.splitOn " " |>.filter (· != "")).mapM fun value =>
    match value.toNat? with
    | some number => pure number
    | none => .error s!"Expected natural number: {value}"
  match numbers with
  | width :: values =>
    if width = 0 then throw "Expected positive lane width"
    if values.any (· ≥ 256) then throw "Expected bytes"
    return String.intercalate " "
      ((encodedLanes width (values.map (BitVec.ofNat 8))).map (fun byte => toString byte.toNat))
  | [] => throw "Expected lane width and bytes"

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
