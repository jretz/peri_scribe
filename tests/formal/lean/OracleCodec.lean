import PeriScribe.CacheCodec

open PeriScribe.CacheCodec

def numbers (text : String) : Except String (List Nat) :=
  (text.splitOn " " |>.filter (· != "")).mapM fun value =>
    match value.toNat? with
    | some number => pure number
    | none => .error s!"Expected natural number: {value}"

def token (text : String) : Except String Token := do
  match ← numbers text with
  | 0 :: tag :: payload => return .scalar tag payload
  | [1, tag] => return .empty tag
  | [2, tag] => return .branch tag
  | _ => throw "Expected scalar, empty, or branch token"

def tokens (text : String) : Except String (List Token) :=
  if text.isEmpty then pure [] else (text.splitOn ";").mapM token

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | [left, right] =>
    let first ← tokens left
    let second ← tokens right
    let one := read first
    let two := read second
    let result := [one.isSome, two.isSome, decide (one = two), decide (first = second)]
    return String.intercalate " " (result.map fun item => if item then "1" else "0")
  | _ => throw "Expected two token sequences"

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
