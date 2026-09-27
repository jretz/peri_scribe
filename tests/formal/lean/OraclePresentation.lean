import PeriScribe.IdentityOutput
import PeriScribe.SparseEvidence

namespace PeriScribe.PresentationOracle

def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => pure value
  | none => .error s!"Expected integer: {text}"

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => .error s!"Expected natural number: {text}"

def optional (text : String) : Except String (Option Int) :=
  if text = "n" then pure none else some <$> integer text

def values (text : String) : List String :=
  text.trimAscii.toString.splitOn " " |>.filter (· != "")

def perimeter (text : String) : Except String SparseEvidence.Perimeter := do
  match text.splitOn "," with
  | [measured, supplied] => return ⟨← optional measured, ← optional supplied⟩
  | _ => throw "Expected measured,supplied"

def report (text : String) : Except String SparseEvidence.Report := do
  match text.splitOn "," with
  | [size, discovery, final] =>
    return ⟨← optional size, ← optional discovery, ← optional final⟩
  | _ => throw "Expected size,discovery,final"

def edge (text : String) : Except String Grouping.Edge := do
  match text.splitOn "," with
  | [first, second] => return (← natural first, ← natural second)
  | _ => throw "Expected two grouping vertices"

def observation (text : String) : Except String IdentityOutput.Observation := do
  match text.splitOn "," with
  | [vertex, time, serial, eligible, area] =>
    let vertex ← natural vertex
    if eligible != "0" && eligible != "1" then throw "Expected Boolean eligibility"
    return ⟨vertex, some vertex, vertex, ← natural time, ← natural serial,
      eligible == "1", ← integer area⟩
  | _ => throw "Expected vertex,time,serial,eligible,area"

def keyed (text : String) : Except String IdentityOutput.Observation := do
  match text.splitOn "," with
  | [identifier, name, serial] =>
    let identifier ← if identifier = "n" then pure none
      else some <$> natural identifier
    return ⟨0, identifier, ← natural name, 0, ← natural serial, true, 0⟩
  | _ => throw "Expected identifier,name,serial"

def optionalText (value : Option Int) : String :=
  toString (value.getD (-99999999))

def naturalText (values : List Nat) : String :=
  String.intercalate " " (values.map toString)

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | [header, rawPerimeters, rawPoints, rawIncidents] =>
    match values header with
    | "sparse" :: areas =>
      let dated ← areas.mapM integer
      let perimeters ← (values rawPerimeters).mapM perimeter
      let points ← (values rawPoints).mapM report
      let incidents ← (values rawIncidents).mapM report
      let current := SparseEvidence.latest dated perimeters points
      let historical := SparseEvidence.historical dated perimeters points incidents
      return s!"{optionalText current} {optionalText historical} " ++
        (if SparseEvidence.visible 25 historical then "1" else "0")
    | _ => throw "Expected sparse header"
  | [header, parameters, rawRows] =>
    match values header with
    | ["matched", name] =>
      let identifiers ← (values parameters).mapM natural
      let rows ← (values rawRows).mapM keyed
      return naturalText
        ((IdentityOutput.matched identifiers (← natural name) rows).map (·.serial))
    | ["compose", representative] =>
      let edges ← (values parameters).mapM edge
      let rows ← (values rawRows).mapM observation
      let owner := Grouping.labels edges (← natural representative)
      let selected := IdentityOutput.grouped edges owner rows
      let drawn := IdentityOutput.drawable edges owner rows
      return naturalText ([selected.length] ++ selected.map (·.serial) ++
        [drawn.length] ++ drawn.map (·.serial) ++ drawn.map (·.time) ++
        [if IdentityOutput.qualified 25 selected then 1 else 0]) ++ " " ++
        optionalText (drawn.getLast?.map (·.area)) ++ " " ++
        optionalText (SparseEvidence.maximum (drawn.map (·.area)))
    | ["keyed", kind, owner] =>
      let aliases ← (values parameters).mapM natural
      let rows ← (values rawRows).mapM keyed
      let owner ← natural owner
      let key := if kind = "id" then IdentityOutput.Key.identifier owner
        else IdentityOutput.Key.name owner
      let selected := IdentityOutput.history
        (fun identifier => (aliases[identifier]?).getD identifier) key rows
      return naturalText (selected.map (·.serial))
    | _ => throw "Expected composition or tagged-key selection"
  | _ => throw "Unexpected number of presentation sections"

end PeriScribe.PresentationOracle

/-- Transport evaluates the same definitions used by the presentation proofs. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.PresentationOracle.respond line.trimAscii.toString with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
