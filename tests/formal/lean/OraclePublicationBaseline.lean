import PeriScribe.PublicationBaseline

namespace PeriScribe.PublicationBaselineOracle

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => throw s!"Invalid natural: {text}"

def optional (text : String) : Except String (Option Nat) :=
  if text = "n" then pure none else some <$> natural text

def aliases (text : String) : Except String (List Nat) :=
  if text = "n" then pure [] else (text.splitOn ":").mapM natural

def entry (text : String) : Except String PublicationBaseline.IndexEntry := do
  match text.splitOn "," with
  | [identifier, name, names] =>
    return ⟨← optional identifier, ← aliases names, ← natural name⟩
  | _ => throw "Expected identifier,name,aliases"

def source (text : String) : Except String PublicationBaseline.Source := do
  match text.splitOn "," with
  | [file, object, identity, names] =>
    return ⟨← natural file, ← optional object, ← aliases names, ← natural identity⟩
  | _ => throw "Expected file,object,identity,aliases"

def row (text : String) : Except String PublicationBaseline.Row := do
  match text.splitOn "," with
  | [identifier, name, file, object, names] =>
    return ⟨← optional identifier, ← natural name, ← aliases names,
      ← natural file, ← optional object⟩
  | _ => throw "Expected identifier,name,file,object,aliases"

def ownerNumbers : PublicationBaseline.Owner → List Int
  | .identified key => [0, key]
  | .anonymous name => [1, name]

def fireNumbers (index : List PublicationBaseline.IndexEntry)
    (rows : List PublicationBaseline.Evidence) (key : PublicationBaseline.Owner) :
    List Int :=
  match PublicationBaseline.baseline rows key with
  | none => []
  | some fire =>
    let names := fire.aliases.eraseDups.mergeSort
    ownerNumbers key ++ [Int.ofNat fire.name,
      (PublicationBaseline.displayed index key fire).map Int.ofNat |>.getD (-1),
      Int.ofNat names.length] ++ names.map Int.ofNat

def words (text : String) : List String :=
  text.trimAscii.toString.splitOn " " |>.filter (· != "")

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | ["baseline", entries, sources, rows] =>
    let index ← (words entries).mapM entry
    let raw ← (words sources).mapM source
    let displayed ← (words rows).mapM row
    match PublicationBaseline.resolveAll raw displayed with
    | none => return "-1"
    | some joined =>
      let keys := PublicationBaseline.keys joined
      let values : List Int := Int.ofNat keys.length ::
        keys.flatMap (fireNumbers index joined)
      return String.intercalate " " (values.map toString)
  | _ => throw "Expected baseline|index|sources|rows"

end PeriScribe.PublicationBaselineOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.PublicationBaselineOracle.respond line.trimAscii.toString with
    | .ok result => output.putStrLn result
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
