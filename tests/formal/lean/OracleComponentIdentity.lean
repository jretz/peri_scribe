import PeriScribe.ComponentIdentity

namespace PeriScribe.ComponentIdentityOracle

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => throw s!"Invalid natural: {text}"

def optional (text : String) : Except String (Option Nat) :=
  if text = "n" then pure none else some <$> natural text

def numbers (text : String) : Except String (List Nat) :=
  ((text.splitOn " ").filter (· != "")).mapM natural

def encodedKey : ComponentIdentity.Key → String
  | .identifier value => s!"0 {value}"
  | .component value => s!"1 {value}"
  | .name value => s!"2 {value}"

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | ["anchor", values] =>
    return toString (((ComponentIdentity.anchor (← numbers values)).map Int.ofNat)
      |>.getD (-1))
  | ["key", identifier, component, name] =>
    return encodedKey (ComponentIdentity.key (← optional identifier)
      (← optional component) (← natural name))
  | ["aliases", identifier, component, name] =>
    return String.intercalate " " ((ComponentIdentity.aliases (← optional identifier)
      (← optional component) (← natural name)).map encodedKey)
  | ["select", owner, values] =>
    let rows := (← numbers values).zipIdx |>.map fun (component, position) =>
      ComponentIdentity.Row.mk position (.component component) position
    return String.intercalate " " ((ComponentIdentity.history
      (.component (← natural owner)) rows).map (toString ∘ ComponentIdentity.Row.datum))
  | ["components", values] =>
    return String.intercalate " " ((ComponentIdentity.componentAliases
      (← numbers values)).map encodedKey)
  | ["storage", kind, values] =>
    let payload ← numbers values
    let value ← match kind with
      | "id" => pure (ComponentIdentity.StorageKey.identifier payload)
      | "name" => pure (.name payload)
      | "component" => pure (.component payload)
      | _ => throw "Unknown storage key kind"
    return String.intercalate " " ((ComponentIdentity.encode value).map toString)
  | _ => throw "Invalid component-identity operation"

end PeriScribe.ComponentIdentityOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.ComponentIdentityOracle.respond line.trimAscii.toString with
    | .ok result => output.putStrLn result
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
