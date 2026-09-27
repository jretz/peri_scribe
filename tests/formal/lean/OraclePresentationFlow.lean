import PeriScribe.GeometrySharing
import PeriScribe.UpdateViewer

namespace PeriScribe.PresentationFlowOracle

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => throw s!"Expected natural number: {text}"

def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => pure value
  | none => throw s!"Expected integer: {text}"

def optional (text : String) : Except String (Option Nat) :=
  if text = "-" then pure none else some <$> natural text

def entry (text : String) : Except String GeometrySharing.Entry := do
  match text.splitOn "," with
  | [digest, payload] => return (← natural digest, ← natural payload)
  | _ => throw "Expected digest,payload"

def treeText : GeometrySharing.Tree → List Nat
  | .leaf digest payloads => [0, digest, payloads.length] ++ payloads
  | .branch digest split smaller larger =>
    [1, digest, split] ++ treeText smaller ++ treeText larger

def row (text : String) : Except String UpdateViewer.Row := do
  match text.splitOn "," with
  | [serial, time, identifier, name, kind, key, area] =>
    return ⟨← natural serial, ← integer time, ← optional identifier, ← natural name,
      ← (if kind = "-" then pure none else
        return some (← natural kind, ← natural key)), ← natural area⟩
  | _ => throw "Expected serial,time,identifier,name,kind,key,area"

def visible (text : String) : Except String UpdateViewer.Visible := do
  match text.splitOn "," with
  | [token, kind, owner, name, age, matching] =>
    return ⟨← natural token, (← natural kind, ← natural owner), ← natural name,
      ← integer age, (← natural matching) != 0⟩
  | _ => throw "Expected token,kind,owner,name,age,matching"

def integers (values : List Int) : String :=
  String.intercalate " " (values.map toString)

def naturals (values : List Nat) : String := integers (values.map Int.ofNat)

def ownership (text : String) :
    Except String (UpdateViewer.Key × UpdateViewer.Key) := do
  match text.splitOn "," with
  | [kind, key, ownerKind, ownerKey] =>
    return ((← natural kind, ← natural key), (← natural ownerKind, ← natural ownerKey))
  | _ => throw "Expected kind,key,ownerKind,ownerKey"

def respond (words : List String) : Except String String := do
  match words with
  | "tree" :: entries =>
    match ← entries.mapM entry with
    | [] => return "2"
    | first :: rest => return naturals (treeText (GeometrySharing.build first rest))
  | "lookup" :: digest :: payload :: entries =>
    let query := (← natural digest, ← natural payload)
    match ← entries.mapM entry with
    | [] => return "0"
    | first :: rest =>
      let tree := GeometrySharing.build first rest
      return if query.2 ∈ GeometrySharing.lookup tree query.1 then "1" else "0"
  | "snapshot" :: now :: width :: rows =>
    let updates := UpdateViewer.snapshot (← integer now) (← integer width)
      (← rows.mapM row)
    return integers (updates.flatMap fun update =>
      [update.row.serial, update.baseline.map Int.ofNat |>.getD (-1)])
  | "projected-snapshot" :: now :: width :: values =>
    let (assignments, tail) := values.span (· != "--")
    let owners ← assignments.mapM ownership
    let projection := fun key => (owners.find? (fun item => item.1 == key)).map Prod.snd
    let updates := UpdateViewer.projectedSnapshot projection (← integer now)
      (← integer width) (← tail.drop 1 |>.mapM row)
    return integers (updates.flatMap fun update =>
      let original := UpdateViewer.identity update.row
      [update.row.serial, original.1, original.2, update.owner.1, update.owner.2,
        update.baseline.map Int.ofNat |>.getD (-1)])
  | "group" :: index :: byName :: rows =>
    let selected := UpdateViewer.selected (← natural index) (← rows.mapM visible)
    let sorted := UpdateViewer.ordered ((← natural byName) != 0) selected
    return naturals ((UpdateViewer.owners selected).length ::
      sorted.length :: sorted.map (·.token))
  | "reuse" :: values =>
    let (old, tail) := values.span (· != "--")
    let previous ← old.mapM entry
    let requested ← tail.drop 1 |>.mapM natural
    return integers ((UpdateViewer.reconcile previous requested).flatMap fun pair =>
      [pair.1, pair.2.map Int.ofNat |>.getD (-1)])
  | _ => throw s!"Unknown presentation-flow request: {words}"

end PeriScribe.PresentationFlowOracle

/-- Execute the proved trie, retained-history, and DOM occurrence definitions. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    let words := line.trimAscii.toString.splitOn " "
    match PeriScribe.PresentationFlowOracle.respond words with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
