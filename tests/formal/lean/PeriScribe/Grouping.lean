import Std

namespace PeriScribe.Grouping

abbrev Edge := Nat × Nat

/-- The specification admits exactly finite undirected paths through supplied edges. -/
inductive Connected (edges : List Edge) : Nat → Nat → Prop
  | same (node : Nat) : Connected edges node node
  | edge {left right : Nat} : (left, right) ∈ edges → Connected edges left right
  | reverse {left right : Nat} : Connected edges left right → Connected edges right left
  | join {left middle right : Nat} :
      Connected edges left middle → Connected edges middle right →
      Connected edges left right

/-- Replacing an entire representative class is the extensional union operation. -/
def merge (labels : Nat → Nat) (edge : Edge) (node : Nat) : Nat :=
  if labels node = labels edge.2 then labels edge.1 else labels node

/-- Edge order affects representatives, while the partition must remain invariant. -/
def labels : List Edge → Nat → Nat
  | [] => id
  | edge :: rest => merge (labels rest) edge

theorem merge_preserves_existing_class (before : Nat → Nat) (edge : Edge)
    (left right : Nat) (same : before left = before right) :
    merge before edge left = merge before edge right := by
  simp [merge, same]

theorem merge_joins_requested_class (before : Nat → Nat) (edge : Edge) :
    merge before edge edge.1 = merge before edge edge.2 := by
  simp [merge]

theorem connected_mono {before after : List Edge}
    (included : ∀ edge ∈ before, edge ∈ after) {left right : Nat}
    (connected : Connected before left right) : Connected after left right := by
  induction connected with
  | same => exact .same _
  | edge member => exact .edge (included _ member)
  | reverse _ induction => exact .reverse induction
  | join _ _ first second => exact .join first second

theorem labels_sound (edges : List Edge) (left right : Nat)
    (same : labels edges left = labels edges right) : Connected edges left right := by
  induction edges generalizing left right with
  | nil =>
    have equal : left = right := same
    subst right
    exact .same _
  | cons edge rest induction =>
    have prior {a b : Nat} (equal : labels rest a = labels rest b) :
        Connected (edge :: rest) a b :=
      connected_mono (fun _ member => List.mem_cons_of_mem edge member)
        (induction a b equal)
    have link : Connected (edge :: rest) edge.1 edge.2 := .edge (by simp)
    by_cases first : labels rest left = labels rest edge.2
    · by_cases second : labels rest right = labels rest edge.2
      · exact prior (first.trans second.symm)
      · simp only [labels, merge, first, second, ite_true, ite_false] at same
        exact .join (prior first) (.join (.reverse link) (prior same))
    · by_cases second : labels rest right = labels rest edge.2
      · simp only [labels, merge, first, second, ite_true, ite_false] at same
        exact .join (prior same) (.join link (prior second.symm))
      · simp only [labels, merge, first, second, ite_false] at same
        exact prior same

theorem labels_join_every_edge (edges : List Edge) (edge : Edge)
    (present : edge ∈ edges) : labels edges edge.1 = labels edges edge.2 := by
  induction edges with
  | nil => simp at present
  | cons first rest induction =>
    rcases List.mem_cons.mp present with equal | member
    · subst edge
      exact merge_joins_requested_class _ _
    · exact merge_preserves_existing_class _ _ _ _ (induction member)

theorem labels_complete (edges : List Edge) {left right : Nat}
    (connected : Connected edges left right) :
    labels edges left = labels edges right := by
  induction connected with
  | same => rfl
  | edge member => exact labels_join_every_edge _ _ member
  | reverse _ induction => exact induction.symm
  | join _ _ first second => exact first.trans second

theorem union_computes_connected_components (edges : List Edge) (left right : Nat) :
    labels edges left = labels edges right ↔ Connected edges left right :=
  ⟨labels_sound edges left right, labels_complete edges⟩

theorem edge_order_and_duplicates_do_not_change_partition
    (first second : List Edge)
    (sameEdges : ∀ edge, edge ∈ first ↔ edge ∈ second) (left right : Nat) :
    labels first left = labels first right ↔
      labels second left = labels second right := by
  rw [union_computes_connected_components, union_computes_connected_components]
  exact ⟨connected_mono (fun edge member => (sameEdges edge).mp member),
    connected_mono (fun edge member => (sameEdges edge).mpr member)⟩

/-- Path halving changes parent pointers but preserves their representative class. -/
def halve (parent : Nat → Nat) (node : Nat) (index : Nat) : Nat :=
  if index = node then parent (parent node) else parent index

theorem path_halving_preserves_representatives (parent root : Nat → Nat)
    (consistent : ∀ index, root (parent index) = root index) (node index : Nat) :
    root (halve parent node index) = root index := by
  by_cases equal : index = node
  · subst index
    simp [halve, consistent]
  · simp [halve, equal, consistent]

/-- Production union changes only the losing root's parent pointer. -/
def linkRoots (parent : Nat → Nat) (winner loser node : Nat) : Nat :=
  if node = loser then winner else parent node

theorem root_link_preserves_merged_partition (parent root : Nat → Nat)
    (consistent : ∀ node, root (parent node) = root node)
    (winner loser : Nat) (winningRoot : root winner = winner)
    (losingRoot : root loser = loser) (node : Nat) :
    merge root (winner, loser) (linkRoots parent winner loser node) =
      merge root (winner, loser) node := by
  by_cases linked : node = loser
  · subst node
    simp [linkRoots, merge, winningRoot, losingRoot]
  · simp only [linkRoots, linked, ite_false]
    exact merge_preserves_existing_class root _ _ _ (consistent node)

theorem linking_joins_both_roots (root : Nat → Nat) (winner loser : Nat) :
    merge root (winner, loser) winner = merge root (winner, loser) loser :=
  merge_joins_requested_class root (winner, loser)

/-- A concrete representative table evaluates each union once per vertex. -/
def tableLabels (count : Nat) : List Edge → List Nat
  | [] => List.range count
  | edge :: rest =>
    let previous := tableLabels count rest
    let root := fun node => (previous[node]?).getD node
    (List.range count).map (merge root edge)

theorem table_union_refines_union (count : Nat) (edges : List Edge)
    (valid : ∀ edge ∈ edges, edge.1 < count ∧ edge.2 < count)
    (node : Nat) (inside : node < count) :
    ((tableLabels count edges)[node]?).getD node = labels edges node := by
  induction edges generalizing node with
  | nil => simp [tableLabels, labels, inside]
  | cons edge rest induction =>
    have bounded := valid edge (by simp)
    have previous := induction (fun item member => valid item (by simp [member]))
    simp only [tableLabels, List.getElem?_map, List.getElem?_range inside,
      Option.map_some, Option.getD_some, labels, merge]
    rw [previous node inside, previous edge.1 bounded.1, previous edge.2 bounded.2]

/-- Canonical component labels permit comparison despite union order and root choice. -/
def canonical (count : Nat) (edges : List Edge) : List Nat :=
  let table := tableLabels count edges
  (List.range count).map fun node =>
    ((List.range count).find? (fun other =>
      (table[other]?).getD other == (table[node]?).getD node)).getD node

end PeriScribe.Grouping
