import PeriScribe.LogSeeking

open PeriScribe.LogSeeking

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => throw s!"Invalid natural number: {text}"

def record (text : String) : Except String Record := do
  match text.splitOn ":" with
  | [width, timestamp, inclusion] =>
    let bytes ← natural width
    if bytes = 0 then throw "Complete records must have positive byte lengths"
    let time ← if timestamp = "-" then pure none else some <$> natural timestamp
    if inclusion != "0" && inclusion != "1" then throw "Invalid inclusion flag"
    return ⟨bytes, time, inclusion = "1", 0⟩
  | _ => throw "Expected byte-length:timestamp:inclusion"

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | [cutoff, upper, unfinished, body] =>
    let since ← natural cutoff
    let upperBound ← if upper = "-" then pure none else some <$> natural upper
    let tail ← natural unfinished
    let parsed ← if body.isEmpty then pure [] else (body.splitOn ";").mapM record
    let records := parsed.zipIdx.map fun (item, index) => {item with serial := index}
    let start := seek since records tail
    let searched := binarySearch (fun query => timestampProbe since 0 query records)
      (size records + tail + 1) 0 (size records + tail)
    let plain := safeWindow since upperBound (dropBytes start records)
    let compressed := safeWindow since upperBound records
    let values := [start, searched, plain.length] ++ plain.map Record.serial ++
      [compressed.length] ++ compressed.map Record.serial
    return String.intercalate " " (values.map toString)
  | _ => throw "Expected cutoff|upper|unfinished-bytes|records"

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
