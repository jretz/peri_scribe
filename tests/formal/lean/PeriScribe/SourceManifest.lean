import PeriScribe.SourceDigest

namespace PeriScribe.SourceManifest

/-- Exactly two fields per occurrence preserve pair boundaries without another tag. -/
def flattenPairs : List (α × α) → List α
  | [] => []
  | (path, content) :: rest => path :: content :: flattenPairs rest

theorem flatten_pairs_injective (first second : List (α × α))
    (same : flattenPairs first = flattenPairs second) : first = second := by
  induction first generalizing second with
  | nil =>
    cases second with
    | nil => rfl
    | cons pair rest => cases same
  | cons pair rest induction =>
    cases second with
    | nil => cases same
    | cons other remaining =>
      cases pair with
      | mk path content =>
        cases other with
        | mk otherPath otherContent =>
          simp only [flattenPairs, List.cons.injEq] at same
          obtain ⟨rfl, rfl, sameTail⟩ := same
          rw [induction remaining sameTail]

/-- The complete ordered input identity uses the proved prefix-free field encoding. -/
def inventoryFields (entries : List (List Nat × List Nat)) : List Nat :=
  SourceDigest.fields (flattenPairs entries)

theorem inventory_fields_injective (first second : List (List Nat × List Nat))
    (same : inventoryFields first = inventoryFields second) : first = second := by
  exact flatten_pairs_injective first second
    (SourceDigest.fields_injective _ _ same)

/-- Ordered constructors retain empty inventories, paths, contents and multiplicity. -/
inductive Tree (Path Content : Type) where
  | empty : Tree Path Content
  | leaf : Path → Content → Tree Path Content
  | branch : Tree Path Content → Tree Path Content → Tree Path Content

/-- Domain-separated framing must distinguish these constructors before hashing. -/
inductive Node (Path Content Digest : Type) where
  | empty : Node Path Content Digest
  | leaf : Path → Content → Node Path Content Digest
  | branch : Digest → Digest → Node Path Content Digest

/-- Completed branches depend on the exact ordered identities of both children. -/
def root (hash : Node Path Content Digest → Digest) : Tree Path Content → Digest
  | .empty => hash .empty
  | .leaf path content => hash (.leaf path content)
  | .branch left right => hash (.branch (root hash left) (root hash right))

/-- Execute the same root definition while retaining its constructor and child order. -/
def constructorTokens (tree : Tree Nat Nat) : List Nat :=
  root (fun node => match node with
    | .empty => [2]
    | .leaf path content => [0, path, content]
    | .branch left right => 1 :: (left ++ right)) tree

/-- Collision freedom is an explicit ideal-hash premise, not a theorem about SHA-256. -/
theorem root_retains_complete_ordered_tree
    (hash : Node Path Content Digest → Digest) (collisionFree : Function.Injective hash)
    (first second : Tree Path Content) (same : root hash first = root hash second) :
    first = second := by
  induction first generalizing second with
  | empty =>
    cases second with
    | empty => rfl
    | leaf path content => cases collisionFree same
    | branch left right => cases collisionFree same
  | leaf path content =>
    cases second with
    | empty => cases collisionFree same
    | leaf otherPath otherContent =>
      have equal := Node.leaf.inj (collisionFree same)
      cases equal.1
      cases equal.2
      rfl
    | branch left right => cases collisionFree same
  | branch left right leftInduction rightInduction =>
    cases second with
    | empty => cases collisionFree same
    | leaf path content => cases collisionFree same
    | branch otherLeft otherRight =>
      have equal := Node.branch.inj (collisionFree same)
      have leftEqual := leftInduction otherLeft equal.1
      have rightEqual := rightInduction otherRight equal.2
      cases leftEqual
      cases rightEqual
      rfl

/-- Memoized branch identity agrees with recomputation when its children match. -/
theorem cached_branch_refines_recomputation
    (hash : Node Path Content Digest → Digest)
    (beforeLeft beforeRight afterLeft afterRight : Digest)
    (sameLeft : beforeLeft = afterLeft) (sameRight : beforeRight = afterRight) :
    hash (.branch beforeLeft beforeRight) = hash (.branch afterLeft afterRight) := by
  simp [sameLeft, sameRight]

end PeriScribe.SourceManifest
