import PeriScribe.SpatialOverlap
import PeriScribe.DifferentialRows
import PeriScribe.CoordinateQuantization

namespace PeriScribe.SpatialOracle

def integer (value : String) : Except String Int :=
  match value.toInt? with
  | some result => pure result
  | none => throw s!"Expected integer: {value}"

def natural (value : String) : Except String Nat :=
  match value.toNat? with
  | some result => pure result
  | none => throw s!"Expected natural: {value}"

def optional (value : String) : Except String (Option Int) :=
  if value = "n" then pure none else some <$> integer value

def mask (cells : List Nat) : Nat :=
  cells.eraseDups.foldl (fun value cell => value + 2 ^ cell) 0

def cells (value : Nat) : List Nat :=
  (List.range 4).filter (fun cell => value / 2 ^ cell % 2 == 1)

def box (value : String) : Except String SpatialOverlap.Box := do
  match value.splitOn "," with
  | [left, bottom, right, top] =>
    return ⟨← integer left, ← integer bottom, ← integer right, ← integer top⟩
  | _ => throw "Expected four rectangle bounds"

def shape (value : String) : Except String SpatialOverlap.Shape :=
  if value = "n" then pure [] else (value.splitOn ":").mapM box

def shapes (value : String) : Except String (List SpatialOverlap.Shape) :=
  if value = "empty" then pure [] else (value.splitOn ";").mapM shape

def source (value : String) : Except String (DifferentialRows.Source × List Nat) := do
  match value.splitOn "," with
  | [identity, time, footprint, first, second, third, fourth] =>
    let values ← [first, second, third, fourth].mapM optional
    return (⟨← natural identity, ← optional time,
      fun key => (values[key]?).getD none⟩, cells (← natural footprint))
  | _ => throw "Expected source identity, time, footprint, and four measurements"

def optionText (value : Option Int) : List String :=
  match value with
  | none => ["0", "0"]
  | some value => ["1", toString value]

def rowText (visible : List Nat) (row : DifferentialRows.Row) : List String :=
  [toString row.group.start, toString row.group.last,
    toString row.group.source.identity, toString (mask row.group.ring),
    if row.group.emitted then "1" else "0",
    if visible.contains row.group.start then "1" else "0"] ++
    optionText row.group.source.time ++
    (List.range 4).flatMap (fun key =>
      optionText (row.group.source.values key) ++ optionText (row.differences key))

def respond (words : List String) : Except String String := do
  match words with
  | ["overlap", queries, features] =>
    let queries := (← shapes queries).zipIdx.map fun (shape, index) =>
      SpatialOverlap.Query.mk index shape
    let matching := SpatialOverlap.indexed queries (← shapes features)
    return String.intercalate " " (matching.mergeSort.map toString)
  | ["quantize", numerator, denominator] =>
    let denominator ← integer denominator
    if denominator ≤ 0 then throw "Expected positive denominator"
    return toString (CoordinateQuantization.nearest (← integer numerator) denominator)
  | "rows" :: omitted :: areas :: entries =>
    let omitted ← if omitted = "n" then pure []
      else (omitted.splitOn ",").mapM natural
    let areas ← (areas.splitOn ",").mapM natural
    if areas.length != 16 then throw "Expected every four-cell area"
    let entries ← entries.mapM source
    let rows := DifferentialRows.build (entries.map Prod.fst) (entries.map Prod.snd)
      omitted
    let visible := (DifferentialRows.visible 1000000
      (fun shape => (areas[mask shape]?).getD 0) rows).map (fun row => row.group.start)
    return String.intercalate " " (rows.flatMap (rowText visible))
  | _ => throw s!"Unknown spatial request: {words}"

end PeriScribe.SpatialOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    let words := (line.trimAscii.toString.splitOn " ").filter (· != "")
    match PeriScribe.SpatialOracle.respond words with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
