import PeriScribe.SourceValidation

open PeriScribe.SourceValidation

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => .error s!"Expected a natural token: {text}"

def numbers (text : String) : Except String (List Nat) :=
  (text.splitOn " " |>.filter (· != "")).mapM natural

def pairs : List Nat → Except String (List (Nat × Nat))
  | [] => pure []
  | first :: second :: rest => return (first, second) :: (← pairs rest)
  | _ => .error "Expected paired column/value tokens"

def row (text : String) : Except String Row := do
  match ← (text.splitOn ",").mapM natural with
  | key :: geometry :: attributes => return ⟨key, ← pairs attributes, geometry⟩
  | _ => throw "Expected key,geometry,attributes"

def frame (reference columns rows : String) : Except String Frame := do
  let known ← if reference == "n" then pure none else some <$> natural reference
  return ⟨← numbers columns, known,
    ← (rows.splitOn " " |>.filter (· != "")).mapM row⟩

def packed (values : List Nat) : List Nat :=
  let sorted := values.mergeSort (· ≤ ·)
  sorted.length :: sorted

def respond (line : String) : Except String (List Nat) := do
  match line.splitOn "|" with
  | ["validate", oneReference, oneColumns, oneRows,
      twoReference, twoColumns, twoRows] =>
    let complete ← frame oneReference oneColumns oneRows
    let stored ← frame twoReference twoColumns twoRows
    return [if accepts complete stored then 1 else 0,
      if compatible complete stored then 0 else 1] ++
      packed (missing complete stored) ++ packed (mismatched complete stored) ++
      packed (missingColumns complete stored) ++ packed (duplicates complete.rows) ++
      packed (duplicates stored.rows)
  | _ => throw "Expected validate request"

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
