import PeriScribe.IdentityLifecycle

open PeriScribe.IdentityLifecycle

namespace OwnershipOracle

def numbers (text : String) : Except String (List Nat) :=
  (text.splitOn " " |>.filter (· != "")).mapM fun value =>
    match value.toNat? with
    | some number => pure number
    | none => .error s!"Expected natural number: {value}"

def number (text : String) : Except String Nat := do
  match ← numbers text with
  | [value] => return value
  | _ => throw "Expected one natural number"

def optional (text : String) : Except String (Option Nat) :=
  if text = "-1" then pure none else some <$> number text

structure Current where
  fire : PeriScribe.Identity.Fire
  aliases : List Nat
  requested : Nat
  collision : Bool

def current (text : String) : Except String Current := do
  match text.splitOn "/" with
  | [key, name, preferred, aliases, requested, collision, signatures, sources] =>
    return ⟨⟨← number key, ← number name, ← numbers signatures, ← numbers sources,
      ← optional preferred⟩, ← numbers aliases, ← number requested, collision == "1"⟩
  | _ => throw "Expected complete current identity evidence"

def history (text : String) : Except String PeriScribe.Identity.History := do
  match text.splitOn "/" with
  | [key, names, signatures, sources, localAliases] =>
    return ⟨← number key, ← numbers names, ← numbers signatures, ← numbers sources,
      ← numbers localAliases⟩
  | _ => throw "Expected historical identity evidence"

def pairs (text : String) : Except String (List (Nat × Nat)) :=
  (text.splitOn ";" |>.filter (· != "")).mapM fun entry => do
    match ← numbers entry with
    | [alias, key] => return (alias, key)
    | _ => throw "Expected alias and owner"

def lookup (entries : List (Nat × Nat)) (key : Nat) : Option Nat :=
  (entries.find? (fun entry => entry.1 == key)).map Prod.snd

def respond (line : String) : Except String (List Nat) := do
  match line.splitOn "|" with
  | ["resolve", base, reservedIdentifiers, perimeterKeys, historical,
      bindings, histories, fires] =>
    let base ← number base
    let perimeterKeys ← numbers perimeterKeys
    let historical ← numbers historical
    let reservedIdentifiers ← numbers reservedIdentifiers
    let aliases ← pairs bindings
    let histories ← (histories.splitOn ";" |>.filter (· != "")).mapM history
    let fires ← (fires.splitOn ";" |>.filter (· != "")).mapM current
    let find := fun key => fires.find? (fun item => item.fire.key == key)
    let aliasOwner := fun alias =>
      (lookup aliases alias).or (if alias ∈ perimeterKeys then some alias else none)
    let fireKeys := fires.map (fun item => item.fire.key)
    let known := fun key => (find key).bind fun item =>
      PeriScribe.Identity.stable item.aliases aliasOwner
    let seeking := fires.filter (fun item => (known item.fire.key).isNone)
    let unnamed := (seeking.filter (fun item => item.aliases.isEmpty)).map
      (fun item => item.fire.key)
    let identified := (seeking.filter (fun item => !item.aliases.isEmpty)).map
      (fun item => item.fire.key)
    let options := choices histories (fun key => (find key).map Current.fire)
    let fresh := fun key reserved => match find key with
      | some item => freshKey base item.requested item.collision reserved
      | none => freshKey base key false reserved
    let reserved := reservedIdentifiers ++ fireKeys.filterMap known
    let result := resolve fresh fireKeys unnamed identified known reserved historical
        options
    return fireKeys.map (fun key => (result key).getD 0)
  | ["acknowledge", previous, current] =>
    let previous ← numbers previous
    let current ← numbers current
    return acknowledge (fun _ => previous) (fun _ => current) 0
  | ["aliases", previous, current, queries] =>
    let previous ← pairs previous
    let current ← pairs current
    let queries ← numbers queries
    let saved := saveAliases (lookup previous) (lookup current)
    return queries.map (fun key => (saved key).getD 0)
  | ["novel", previous, current] =>
    return [if novel (← numbers previous) (← numbers current) then 1 else 0]
  | _ => throw "Expected complete resolver or acknowledgement request"

end OwnershipOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match OwnershipOracle.respond line.trimAscii.toString with
    | .ok response => output.putStrLn (String.intercalate " " (response.map toString))
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
