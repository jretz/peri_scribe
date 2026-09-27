import PeriScribe.IncrementalCollection
import PeriScribe.PointConstruction

namespace PeriScribe.IngestionOracle

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => throw s!"Expected natural number: {text}"

def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => pure value
  | none => throw s!"Expected integer: {text}"

def boolean (text : String) : Except String Bool :=
  match text with
  | "0" => pure false
  | "1" => pure true
  | _ => throw "Expected Boolean 0 or 1"

def optional (text : String) : Except String (Option Int) :=
  if text = "null" then pure none else some <$> integer text

def row (text : String) : Except String IncrementalCollection.Row := do
  match text.splitOn "," with
  | [id, name, active, modified, geometry] =>
    return ⟨← natural id, ← natural name, ← boolean active, ← optional modified,
      ← natural geometry⟩
  | _ => throw "Expected id,name,active,modified,geometry"

def rows (text : String) : Except String (List IncrementalCollection.Row) :=
  if text = "-" then pure [] else (text.splitOn ";").mapM row

def point (text : String) : Except String SpatialIndex.Point := do
  match text.splitOn "," with
  | [longitude, latitude] => return ⟨← natural longitude, ← natural latitude⟩
  | _ => throw "Expected offset longitude,latitude"

def text (values : List Nat) : String := String.intercalate " " (values.map toString)

def respond (words : List String) : Except String String := do
  match words with
  | ["select", full, cutoff, stored, current] =>
    return text (IncrementalCollection.select (← rows stored) (← rows current)
      (← integer cutoff) (← boolean full))
  | "recent" :: cutoff :: times =>
    return if IncrementalCollection.recent (← integer cutoff) (← times.mapM optional)
      then "1" else "0"
  | "cutoff" :: overlap :: epoch :: times =>
    return toString (IncrementalCollection.cutoff (← times.mapM optional)
      (← integer overlap) (← integer epoch))
  | ["query", full, same] =>
    return if IncrementalCollection.shouldQuery (← boolean full) (← boolean same)
      then "1" else "0"
  | "partition" :: identifier :: points =>
    let input ← points.mapM point
    return text ((PointConstruction.bucket input (← natural identifier)).flatMap
      fun point => [point.longitude, point.latitude])
  | "build" :: identifier :: points =>
    let input ← points.mapM point
    return text ((PointConstruction.buildTile input (← natural identifier)).flatMap
      fun point => [point.longitude, point.latitude])
  | "tiles" :: points =>
    return text (PointConstruction.occupiedTiles (← points.mapM point))
  | _ => throw s!"Unknown ingestion request: {words}"

end PeriScribe.IngestionOracle

/-- Batch transport for the proved ingestion definitions. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.IngestionOracle.respond (line.trimAscii.toString.splitOn " ") with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
