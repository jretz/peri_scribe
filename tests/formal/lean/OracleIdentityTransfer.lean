import PeriScribe.IdentityTransfer

namespace PeriScribe.IdentityTransferOracle

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => throw s!"Invalid natural: {text}"

def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => pure value
  | none => throw s!"Invalid integer: {text}"

def optional (text : String) : Except String (Option Nat) :=
  if text = "n" then pure none else some <$> natural text

def words (text : String) : List String :=
  if text = "n" then [] else text.trimAscii.toString.splitOn " " |>.filter (· != "")

def numbers (text : String) : Except String (List Nat) := (words text).mapM natural

def colonNumbers (text : String) : Except String (List Nat) :=
  if text = "n" ∨ text = "" then pure [] else (text.splitOn ":").mapM natural

def pair (text : String) : Except String (Nat × Nat) := do
  match text.splitOn "," with
  | [first, second] => return (← natural first, ← natural second)
  | _ => throw "Expected natural,natural pair"

def pairs (text : String) : Except String (List (Nat × Nat)) := (words text).mapM pair

def owners (values : List (Nat × Nat)) : IdentityTransfer.Owners := fun history =>
  (values.find? (fun value => value.1 == history)).map Prod.snd

def lineageEntry (text : String) : Except String (Nat × List Nat) := do
  match text.splitOn "," with
  | [alias, histories] => return (← natural alias, ← colonNumbers histories)
  | _ => throw "Expected alias,history-list"

def lineage (text : String) : Except String IdentityTransfer.Lineage := do
  let entries ← (words text).mapM lineageEntry
  return fun alias => entries.filter (fun entry => entry.1 == alias) |>.flatMap Prod.snd

def fire (text : String) : Except String IdentityTransfer.Fire := do
  match text.splitOn "," with
  | [identity, time, aliases, additional] =>
    return ⟨← natural identity,
      ← if time = "n" then pure none else some <$> integer time,
      ← colonNumbers aliases, ← colonNumbers additional⟩
  | _ => throw "Expected identity,time,aliases,additional-histories"

def fires (text : String) : Except String (List IdentityTransfer.Fire) :=
  (words text).mapM fire

def encoded (values : List Int) : String := String.intercalate " " (values.map toString)

def selected (value : Option Nat) : Int := (value.map Int.ofNat).getD (-1)

def encodedSets (queries : List Nat) (result : IdentityTransfer.Lineage) : String :=
  encoded (queries.flatMap fun query =>
    let values := (result query).eraseDups.mergeSort
    Int.ofNat values.length :: values.map Int.ofNat)

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | ["claim", queries, rawLineage, rawFires] =>
    let known ← lineage rawLineage
    let current ← fires rawFires
    return encoded ((← numbers queries).map (fun history =>
      selected (IdentityTransfer.claimant known current history)))
  | ["transfer", queries, previous, rawLineage, rawFires, rawWriters] =>
    let old := owners (← pairs previous)
    let known ← lineage rawLineage
    let current ← fires rawFires
    let writers := owners (← pairs rawWriters)
    if current.any (fun value => (writers value.identity).isNone) then
      throw "Every current claimant requires a writer mapping"
    let result := IdentityTransfer.transfer old known current
      (fun identity => (writers identity).getD identity)
    return encoded ((← numbers queries).map (fun history => selected (result history)))
  | ["inherit", writer, rawOwners, records] =>
    let inherited := IdentityTransfer.inheritedRecords (owners (← pairs rawOwners))
      (← pairs records) (← natural writer)
    return encoded (inherited.mergeSort.map Int.ofNat)
  | ["novel", writer, rawOwners, records, current] =>
    let result := IdentityTransfer.novel (owners (← pairs rawOwners))
      (← pairs records) (← natural writer) (← numbers current)
    return if result then "1" else "0"
  | ["lineage", queries, previous, aliases, histories] =>
    let result := IdentityTransfer.extendLineage (← lineage previous)
      (← numbers aliases) (← numbers histories)
    return encodedSets (← numbers queries) result
  | ["learn", queries, histories, previous, aliases, original, rawOwners, writer] =>
    let result := IdentityTransfer.learn (← lineage previous) (← numbers aliases)
      (← numbers original) (← numbers histories) (owners (← pairs rawOwners))
      (← natural writer)
    return encodedSets (← numbers queries) result
  | ["project", rawOwners, records] =>
    let result := IdentityTransfer.project (owners (← pairs rawOwners))
      (← pairs records)
    return encoded (result.flatMap (fun value =>
      [Int.ofNat value.1, Int.ofNat value.2]))
  | ["ack", previous, current] =>
    let records := IdentityTransfer.acknowledgedRecords (← pairs previous)
      (← pairs current)
    let result := records.mergeSort (fun a b => a.1 < b.1 || (a.1 == b.1 && a.2 ≤ b.2))
    return encoded (result.flatMap (fun value =>
      [Int.ofNat value.1, Int.ofNat value.2]))
  | ["chooseWriter", preferred, won] =>
    return toString (selected (IdentityTransfer.chooseWriter (← numbers won)
      (← optional preferred)))
  | _ => throw "Invalid identity-transfer operation"

end PeriScribe.IdentityTransferOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.IdentityTransferOracle.respond line.trimAscii.toString with
    | .ok result => output.putStrLn result
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
