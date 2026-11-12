import PeriScribe.GeometrySharing
import PeriScribe.GeometryPreparation
import PeriScribe.UpdateViewer
import PeriScribe.SourceManifest
import PeriScribe.RetainedSourceIndex
import PeriScribe.SourceProvenance

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

def treeText (tree : GeometrySharing.Tree) (tail : List Nat := []) : List Nat :=
  match tree with
  | .leaf digest payloads => 0 :: digest :: payloads.length :: (payloads ++ tail)
  | .branch digest split smaller larger =>
    1 :: digest :: split :: treeText smaller (treeText larger tail)

def treePrefixes : List GeometrySharing.Entry → List GeometrySharing.Tree
  | [] => []
  | first :: rest =>
    let initial := GeometrySharing.Tree.leaf first.1 [first.2]
    rest.scanl (fun tree item => GeometrySharing.insert tree item.1 item.2) initial

structure DigestCatalogue where
  positions : Std.HashMap Nat Nat := {}
  values : Array Nat := #[]

def digestCatalogue (entries : List GeometrySharing.Entry) : DigestCatalogue :=
  entries.foldl (fun table (digest, _) =>
    if table.positions.contains digest then table
    else ⟨table.positions.insert digest table.values.size, table.values.push digest⟩) {}

structure TreeCatalogue where
  positions : Std.HashMap GeometrySharing.PackedNode Nat := {}
  nodes : Array GeometrySharing.PackedNode := #[]

abbrev PackTree := StateT TreeCatalogue (Except String)

def digestOrdinal (table : DigestCatalogue) (digest : Nat) : PackTree Nat := do
  match table.positions[digest]? with
  | some ordinal =>
    if table.values[ordinal]? = some digest then return ordinal
    else throw "Digest ordinal has a different value"
  | none => throw "Output digest has no exact input identity"

def internTreeNode (node : GeometrySharing.PackedNode) : PackTree Nat := do
  let table ← get
  match table.positions[node]? with
  | some ordinal =>
    if table.nodes[ordinal]? = some node then return ordinal
    else throw "Tree node ordinal has a different value"
  | none =>
    let ordinal := table.nodes.size
    set ({ positions := table.positions.insert node ordinal,
           nodes := table.nodes.push node } : TreeCatalogue)
    return ordinal

def packTree (digests : DigestCatalogue) : GeometrySharing.Tree → PackTree Nat
  | .leaf digest payloads => do
    internTreeNode (.leaf (← digestOrdinal digests digest) payloads)
  | .branch digest split smaller larger => do
    let ordinal ← digestOrdinal digests digest
    let left ← packTree digests smaller
    let right ← packTree digests larger
    internTreeNode (.branch ordinal split left right)

def packedPrefixes (entries : List GeometrySharing.Entry) : Except String (List Nat) := do
  let (roots, table) ← ((treePrefixes entries).mapM (packTree (digestCatalogue entries))).run {}
  let records := table.nodes.toList.flatMap fun node =>
    let tokens := node.tokens
    tokens.length :: tokens
  return table.nodes.size :: roots.length :: (records ++ roots)

def row (text : String) : Except String UpdateViewer.Row := do
  match text.splitOn "," with
  | [serial, time, identifier, name, kind, key, area, preview] =>
    return ⟨← natural serial, ← integer time, ← optional identifier, ← natural name,
      ← (if kind = "-" then pure none else
        return some (← natural kind, ← natural key)), ← natural area, ← optional preview⟩
  | _ => throw "Expected serial,time,identifier,name,kind,key,area,preview"

def visible (text : String) : Except String UpdateViewer.Visible := do
  match text.splitOn "," with
  | [token, kind, owner, name, age, matching] =>
    return ⟨← natural token, (← natural kind, ← natural owner), ← natural name,
      ← integer age, (← natural matching) != 0⟩
  | _ => throw "Expected token,kind,owner,name,age,matching"

def integers (values : List Int) : String :=
  String.intercalate " " (values.map toString)

def naturals (values : List Nat) : String := integers (values.map Int.ofNat)

/-- Decode only oracle transport; source values remain in the caller's exact table. -/
def manifestTree : Nat → List Nat →
    Except String (SourceManifest.Tree Nat Nat × List Nat)
  | 0, _ => throw "Incomplete manifest tree"
  | _ + 1, 2 :: rest => return (.empty, rest)
  | _ + 1, 0 :: path :: content :: rest => return (.leaf path content, rest)
  | fuel + 1, 1 :: rest => do
    let (left, rest) ← manifestTree fuel rest
    let (right, rest) ← manifestTree fuel rest
    return (.branch left right, rest)
  | _ + 1, _ => throw "Expected manifest constructor"

def ownership (text : String) :
    Except String (UpdateViewer.Key × UpdateViewer.Key) := do
  match text.splitOn "," with
  | [kind, key, ownerKind, ownerKey] =>
    return ((← natural kind, ← natural key), (← natural ownerKind, ← natural ownerKey))
  | _ => throw "Expected kind,key,ownerKind,ownerKey"

def respond (words : List String) : Except String String := do
  match words with
  | "source-path" :: values =>
    let (values, tail) := values.span (· != "--")
    let table ← values.mapM natural
    let keys ← (tail.drop 1).mapM natural
    return naturals (SourceProvenance.trace
      (fun key => (table[key]?).getD 0) (fun _ => none) keys)
  | "changed" :: values =>
    let (nodes, tail) := values.span (· != "--")
    let (before, tail) := (tail.drop 1).span (· != "--")
    let after := tail.drop 1
    return naturals (RetainedSourceIndex.changed (← nodes.mapM natural)
      (← before.mapM entry) (← after.mapM entry))
  | "affected" :: values =>
    let (current, tail) := values.span (· != "--")
    let (changed, tail) := (tail.drop 1).span (· != "--")
    let (before, tail) := (tail.drop 1).span (· != "--")
    let after := tail.drop 1
    return naturals (RetainedSourceIndex.affected (← current.mapM natural)
      (← before.mapM entry) (← after.mapM entry) (← changed.mapM natural))
  | "manifest" :: values =>
    let tokens ← values.mapM natural
    let (tree, rest) ← manifestTree tokens.length tokens
    if rest != [] then throw "Trailing manifest constructors"
    return naturals (SourceManifest.constructorTokens tree)
  | "encoding-position" :: payload :: values =>
    return toString (GeometryPreparation.encodingPosition (← values.mapM natural)
      (← natural payload))
  | "tree-prefixes" :: entries =>
    return naturals ((treePrefixes (← entries.mapM entry)).flatMap fun tree =>
      let tokens := treeText tree
      tokens.length :: tokens)
  | "packed-tree-prefixes" :: entries =>
    return naturals (← packedPrefixes (← entries.mapM entry))
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
