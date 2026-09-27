import Std

namespace PeriScribe.GeometrySharing

/-- Payload tokens stand for complete canonical WKB, never only its digest. -/
abbrev Entry := Nat × Nat

inductive Tree where
  | leaf (digest : Nat) (payloads : List Nat)
  | branch (digest split : Nat) (smaller larger : Tree)
  deriving DecidableEq, Repr

def representative : Tree → Nat
  | .leaf digest _ | .branch digest .. => digest

def rank : Tree → Nat
  | .leaf .. => 0
  | .branch _ split .. => split

def difference (first second : Nat) : Nat :=
  let differing := first ^^^ second
  if differing = 0 then 0 else differing.log2 + 1

def entries : Tree → List Entry
  | .leaf digest payloads => payloads.map (digest, ·)
  | .branch _ _ smaller larger => entries smaller ++ entries larger

def join (tree : Tree) (digest payload split : Nat) : Tree :=
  if representative tree < digest then
    .branch (representative tree) split tree (.leaf digest [payload])
  else .branch (representative tree) split (.leaf digest [payload]) tree

/-- This is the compressed insertion protocol, including splits above an old subtree. -/
def insert (tree : Tree) (digest payload : Nat) : Tree :=
  let differing := difference digest (representative tree)
  match tree with
  | .leaf old payloads =>
    if differing = 0 then
      .leaf old (if payload ∈ payloads then payloads else payloads ++ [payload])
    else join tree digest payload differing
  | .branch old split smaller larger =>
    if split < differing then join tree digest payload differing
    else if digest.testBit (split - 1) then
      .branch old split smaller (insert larger digest payload)
    else .branch old split (insert smaller digest payload) larger

def lookup (tree : Tree) (digest : Nat) : List Nat :=
  match tree with
  | .leaf old payloads => if digest = old then payloads else []
  | .branch _ split smaller larger =>
    if digest.testBit (split - 1) then lookup larger digest else lookup smaller digest

/-- Representation obligations make compressed bit routing correspond to the leaves. -/
def Routed : Tree → Prop
  | .leaf .. => True
  | .branch _ split smaller larger =>
    Routed smaller ∧ Routed larger ∧
    (∀ entry ∈ entries smaller, entry.1.testBit (split - 1) = false) ∧
    (∀ entry ∈ entries larger, entry.1.testBit (split - 1) = true)

def Descending : Nat → Tree → Prop
  | _, .leaf .. => True
  | bound, .branch _ split smaller larger =>
    0 < split ∧ split ≤ bound ∧
      Descending (split - 1) smaller ∧ Descending (split - 1) larger

def height : Tree → Nat
  | .leaf .. => 1
  | .branch _ _ smaller larger => 1 + max (height smaller) (height larger)

theorem difference_zero_iff (first second : Nat) :
    difference first second = 0 ↔ first = second := by
  dsimp only [difference]
  by_cases same : first ^^^ second = 0
  · simp only [same, ↓reduceIte, true_iff]
    apply Nat.eq_of_testBit_eq
    intro index
    have bits := congrArg (fun value : Nat => value.testBit index) same
    simp only [Nat.testBit_xor, Nat.zero_testBit] at bits
    simpa using bits
  · simp only [same, ↓reduceIte, Nat.add_eq_zero_iff, Nat.one_ne_zero, and_false,
      false_iff]
    intro equal
    subst second
    simp at same

theorem join_membership (tree : Tree) (digest payload split : Nat) (entry : Entry) :
    entry ∈ entries (join tree digest payload split) ↔
      entry ∈ entries tree ∨ entry = (digest, payload) := by
  unfold join
  split <;> simp [entries, or_comm]

theorem insertion_preserves_exact_entries (tree : Tree) (digest payload : Nat)
    (entry : Entry) : entry ∈ entries (insert tree digest payload) ↔
      entry ∈ entries tree ∨ entry = (digest, payload) := by
  induction tree with
  | leaf old payloads =>
    by_cases same : difference digest old = 0
    · have equal := (difference_zero_iff digest old).mp same
      subst old
      by_cases present : payload ∈ payloads
      · rcases entry with ⟨key, value⟩
        simp [insert, representative, same, present, entries]
        grind
      · simp [insert, representative, same, present, entries]
    · simpa only [insert, representative, same, ↓reduceIte] using
        join_membership (.leaf old payloads) digest payload
          (difference digest old) entry
  | branch old split smaller larger left right =>
    by_cases above : split < difference digest old
    · simpa only [insert, representative, above, ↓reduceIte] using
        join_membership (.branch old split smaller larger) digest payload
          (difference digest old) entry
    · cases bit : digest.testBit (split - 1) <;>
        simp [insert, representative, above, bit, entries, left, right,
          or_assoc, or_left_comm]
      grind

theorem collision_bucket_preserved (digest first second : Nat) (payloads : List Nat)
    (present : first ∈ payloads) :
    (digest, first) ∈ entries (insert (.leaf digest payloads) digest second) := by
  rw [insertion_preserves_exact_entries]
  exact Or.inl (by simp [entries, present])

theorem different_digest_cannot_replace_payload (tree : Tree) (digest payload : Nat)
    (old : Entry) (different : old.1 ≠ digest) :
    old ∈ entries (insert tree digest payload) ↔ old ∈ entries tree := by
  rw [insertion_preserves_exact_entries]
  constructor
  · intro present
    rcases present with oldPresent | same
    · exact oldPresent
    · subst old; exact False.elim (different rfl)
  · exact Or.inl

theorem lookup_is_exact_leaf_map (tree : Tree) (valid : Routed tree)
    (digest payload : Nat) : payload ∈ lookup tree digest ↔
      (digest, payload) ∈ entries tree := by
  induction tree with
  | leaf old payloads =>
    simp only [lookup, entries, List.mem_map, Prod.mk.injEq]
    split <;> simp_all [eq_comm]
  | branch old split smaller larger left right =>
    rcases valid with ⟨leftValid, rightValid, leftBits, rightBits⟩
    simp only [lookup, entries, List.mem_append]
    cases bit : digest.testBit (split - 1)
    · simp only [Bool.false_eq_true, ↓reduceIte]
      rw [left leftValid]
      have absent : (digest, payload) ∉ entries larger := by
        intro present
        have := rightBits _ present
        simp [bit] at this
      simp [absent]
    · simp only [↓reduceIte]
      rw [right rightValid]
      have absent : (digest, payload) ∉ entries smaller := by
        intro present
        have := leftBits _ present
        simp [bit] at this
      simp [absent]

theorem routed_insertion_refines_map (tree : Tree) (digest payload : Nat)
    (before : Routed tree) (after : Routed (insert tree digest payload))
    (query value : Nat) :
    value ∈ lookup (insert tree digest payload) query ↔
      value ∈ lookup tree query ∨ (query, value) = (digest, payload) := by
  rw [lookup_is_exact_leaf_map _ after, insertion_preserves_exact_entries,
    lookup_is_exact_leaf_map _ before]

/-- A branch is valid exactly when its child representations and routing agree. -/
theorem branch_preserves_representation (digest split : Nat) (smaller larger : Tree)
    (left : Routed smaller) (right : Routed larger)
    (leftBits : ∀ entry ∈ entries smaller, entry.1.testBit (split - 1) = false)
    (rightBits : ∀ entry ∈ entries larger, entry.1.testBit (split - 1) = true) :
    Routed (.branch digest split smaller larger) := ⟨left, right, leftBits, rightBits⟩

theorem untouched_branch_persists (old split digest payload : Nat)
    (smaller larger : Tree) (within : difference digest old ≤ split)
    (right : digest.testBit (split - 1) = true) :
    insert (.branch old split smaller larger) digest payload =
      .branch old split smaller (insert larger digest payload) := by
  simp [insert, representative, Nat.not_lt_of_ge within, right]

theorem depth_bounded_by_digest_width (tree : Tree) (bound : Nat)
    (valid : Descending bound tree) : height tree ≤ bound + 1 := by
  induction tree generalizing bound with
  | leaf digest payloads => simp [height]
  | branch old split smaller larger left right =>
    rcases valid with ⟨positive, bounded, leftValid, rightValid⟩
    have leftBound := left _ leftValid
    have rightBound := right _ rightValid
    simp only [height]
    omega

def build (first : Entry) (rest : List Entry) : Tree :=
  rest.foldl (fun tree entry => insert tree entry.1 entry.2) (.leaf first.1 [first.2])

theorem history_preserves_entries (tree : Tree) (history : List Entry) (entry : Entry) :
    entry ∈ entries (history.foldl (fun t item => insert t item.1 item.2) tree) ↔
      entry ∈ entries tree ∨ entry ∈ history := by
  induction history generalizing tree with
  | nil => simp
  | cons first rest induction =>
    rw [List.foldl_cons, induction, insertion_preserves_exact_entries]
    simp [or_assoc]

theorem build_agrees_with_finite_map (first : Entry) (rest : List Entry)
    (entry : Entry) :
    entry ∈ entries (build first rest) ↔ entry ∈ first :: rest := by
  rcases first with ⟨digest, payload⟩
  simp [build, history_preserves_entries, entries]

theorem insertion_order_independent (first second : List Entry) (initial : Entry)
    (same : ∀ entry, entry ∈ first ↔ entry ∈ second) (entry : Entry) :
    entry ∈ entries (build initial first) ↔ entry ∈ entries (build initial second) := by
  simp [build_agrees_with_finite_map, same]

/-- Prefix agreement includes every bit at or above a compressed subtree boundary. -/
def Above (first second bound : Nat) : Prop :=
  ∀ index, bound ≤ index → first.testBit index = second.testBit index

theorem difference_bounded_iff_prefix (first second bound : Nat) :
    difference first second ≤ bound ↔ Above first second bound := by
  by_cases zero : first ^^^ second = 0
  · have same : first = second := by
      apply (difference_zero_iff first second).mp
      simp [difference, zero]
    subst second
    simp [difference, Above]
  · simp only [difference, zero, ↓reduceIte]
    constructor
    · intro small index beyond
      have low : (first ^^^ second).log2 < index := by omega
      have bits := Nat.testBit_lt_two_pow ((Nat.log2_lt zero).mp low)
      cases one : first.testBit index <;> cases two : second.testBit index <;>
        simp_all [Nat.testBit_xor]
    · intro agreement
      have low : first ^^^ second < 2 ^ bound :=
        Nat.lt_pow_two_of_testBit _ (fun index beyond => by
          simp [Nat.testBit_xor, agreement index beyond])
      have := (Nat.log2_lt zero).mpr low
      omega

theorem prefix_transitive (first second third bound : Nat)
    (one : Above first second bound) (two : Above second third bound) :
    Above first third bound :=
  fun index beyond => (one index beyond).trans (two index beyond)

theorem prefix_symmetric (first second bound : Nat) (same : Above first second bound) :
    Above second first bound := fun index beyond => (same index beyond).symm

theorem prefix_weaken (first second low high : Nat) (same : Above first second low)
    (bounded : low ≤ high) : Above first second high :=
  fun index beyond => same index (by omega)

theorem difference_bit_distinct (first second : Nat)
    (positive : 0 < difference first second) :
    first.testBit (difference first second - 1) ≠
      second.testBit (difference first second - 1) := by
  have zero : first ^^^ second ≠ 0 := by
    intro same
    simp [difference, same] at positive
  have bits := Nat.testBit_log2 zero
  simp only [Nat.testBit_xor] at bits
  simpa [difference, zero] using bits

theorem prefix_division_equal (first second bound : Nat)
    (same : Above first second bound) : first / 2 ^ bound = second / 2 ^ bound := by
  apply Nat.eq_of_testBit_eq
  intro index
  simp only [Nat.testBit_div_two_pow]
  exact same (index + bound) (by omega)

theorem split_bit_orders_keys (first second index : Nat)
    (above : Above first second (index + 1))
    (low : first.testBit index = false) (high : second.testBit index = true) :
    first < second := by
  have same := prefix_division_equal first second (index + 1) above
  rw [Nat.pow_succ] at same
  have quotients : (first / 2 ^ index) / 2 = (second / 2 ^ index) / 2 := by
    simpa [Nat.div_div_eq_div_mul] using same
  have firstBit : (first / 2 ^ index) % 2 = 0 := by
    apply Nat.mod_two_eq_zero_iff_testBit_zero.mpr
    simpa only [Nat.testBit_div_two_pow, Nat.zero_add] using low
  have secondBit : (second / 2 ^ index) % 2 = 1 := by
    simpa [Nat.testBit_eq_decide_div_mod_eq] using high
  have ordered : first / 2 ^ index < second / 2 ^ index := by omega
  by_cases result : first < second
  · exact result
  · have divided := Nat.div_le_div_right (c := 2 ^ index) (Nat.le_of_not_gt result)
    omega

theorem joining_keys_have_opposite_routes (first second : Nat)
    (positive : 0 < difference first second) :
    if first < second then
      first.testBit (difference first second - 1) = false ∧
        second.testBit (difference first second - 1) = true
    else first.testBit (difference first second - 1) = true ∧
      second.testBit (difference first second - 1) = false := by
  have different := difference_bit_distinct first second positive
  have above := (difference_bounded_iff_prefix first second
    (difference first second)).mp (by omega)
  have reverse := prefix_symmetric _ _ _ above
  have step : difference first second - 1 + 1 = difference first second := by omega
  cases firstBit : first.testBit (difference first second - 1) <;>
    cases secondBit : second.testBit (difference first second - 1)
  · simp_all
  · have ordered := split_bit_orders_keys first second (difference first second - 1)
      (by simpa [step] using above) firstBit secondBit
    simp [ordered]
  · have ordered := split_bit_orders_keys second first (difference first second - 1)
      (by simpa [step] using reverse) secondBit firstBit
    simp [Nat.not_lt_of_ge (Nat.le_of_lt ordered)]
  · simp_all

/-- Reachable trees retain a real representative and a common prefix at every node. -/
def Valid : Tree → Prop
  | .leaf _ payloads => payloads ≠ []
  | .branch old split smaller larger =>
    Valid smaller ∧ Valid larger ∧ 0 < split ∧
    rank smaller < split ∧ rank larger < split ∧
    (∀ entry ∈ entries smaller ++ entries larger, Above entry.1 old split) ∧
    (∀ entry ∈ entries smaller, entry.1.testBit (split - 1) = false) ∧
    (∀ entry ∈ entries larger, entry.1.testBit (split - 1) = true) ∧
    ∃ entry ∈ entries smaller ++ entries larger, entry.1 = old

theorem representative_has_entry (tree : Tree) (valid : Valid tree) :
    ∃ entry ∈ entries tree, entry.1 = representative tree := by
  cases tree with
  | leaf digest payloads =>
    cases payloads with
    | nil => simp [Valid] at valid
    | cons first rest => exact ⟨(digest, first), by simp [entries], rfl⟩
  | branch old split smaller larger => exact valid.2.2.2.2.2.2.2.2

theorem valid_tree_has_prefix (tree : Tree) (valid : Valid tree)
    (entry : Entry) (present : entry ∈ entries tree) :
    Above entry.1 (representative tree) (rank tree) := by
  cases tree with
  | leaf digest payloads =>
    simp only [entries, List.mem_map] at present
    obtain ⟨payload, _, rfl⟩ := present
    exact fun _ _ => rfl
  | branch old split smaller larger => exact valid.2.2.2.2.2.1 entry present

theorem valid_tree_routes (tree : Tree) (valid : Valid tree) : Routed tree := by
  induction tree with
  | leaf digest payloads => trivial
  | branch old split smaller larger left right =>
    exact ⟨left valid.1, right valid.2.1, valid.2.2.2.2.2.2.1,
      valid.2.2.2.2.2.2.2.1⟩

theorem valid_tree_descends (tree : Tree) (valid : Valid tree) (bound : Nat)
    (bounded : rank tree ≤ bound) : Descending bound tree := by
  induction tree generalizing bound with
  | leaf digest payloads => trivial
  | branch old split smaller larger left right =>
    obtain ⟨small, large, positive, smallRank, largeRank, _⟩ := valid
    exact ⟨positive, bounded, left small _ (by omega), right large _ (by omega)⟩

theorem join_representative (tree : Tree) (digest payload split : Nat) :
    representative (join tree digest payload split) = representative tree := by
  unfold join
  split <;> rfl

theorem join_rank (tree : Tree) (digest payload split : Nat) :
    rank (join tree digest payload split) = split := by
  unfold join
  split <;> rfl

theorem insertion_keeps_representative (tree : Tree) (digest payload : Nat) :
    representative (insert tree digest payload) = representative tree := by
  cases tree with
  | leaf old payloads =>
    by_cases same : difference digest old = 0
    · simp [insert, representative, same]
    · simpa only [insert, representative, same, ↓reduceIte] using
        join_representative (.leaf old payloads) digest payload (difference digest old)
  | branch old split smaller larger =>
    by_cases above : split < difference digest old
    · simpa only [insert, representative, above, ↓reduceIte] using
        join_representative (.branch old split smaller larger) digest payload
          (difference digest old)
    · cases bit : digest.testBit (split - 1) <;>
        simp [insert, representative, above, bit]

theorem insertion_rank (tree : Tree) (digest payload : Nat) :
    rank (insert tree digest payload) =
      max (rank tree) (difference digest (representative tree)) := by
  cases tree with
  | leaf old payloads =>
    by_cases same : difference digest old = 0
    · simp [insert, representative, rank, same]
    · simpa only [insert, representative, rank, same, ↓reduceIte, Nat.zero_max] using
        join_rank (.leaf old payloads) digest payload (difference digest old)
  | branch old split smaller larger =>
    by_cases above : split < difference digest old
    · simpa only [insert, representative, above, rank, ↓reduceIte,
        Nat.max_eq_right (by omega : split ≤ difference digest old)] using
        join_rank (.branch old split smaller larger) digest payload
          (difference digest old)
    · cases bit : digest.testBit (split - 1) <;>
        simp [insert, representative, above, bit, rank,
          Nat.max_eq_left (by omega : difference digest old ≤ split)]

theorem difference_symmetric (first second : Nat) :
    difference first second = difference second first := by
  simp [difference, Nat.xor_comm]

theorem join_preserves_validity (tree : Tree) (digest payload : Nat)
    (valid : Valid tree) (above : rank tree < difference digest (representative tree)) :
    Valid (join tree digest payload (difference digest (representative tree))) := by
  let split := difference digest (representative tree)
  have positive : 0 < split := by dsimp [split]; omega
  have oldPrefix : ∀ entry ∈ entries tree, Above entry.1 (representative tree) split :=
    fun entry member => prefix_weaken _ _ _ _
      (valid_tree_has_prefix tree valid entry member)
      (by dsimp [split]; omega)
  have newPrefix : Above digest (representative tree) split :=
    (difference_bounded_iff_prefix _ _ _).mp (by omega)
  obtain ⟨witness, member, same⟩ := representative_has_entry tree valid
  have oldBits : ∀ entry ∈ entries tree,
      entry.1.testBit (split - 1) = (representative tree).testBit (split - 1) := by
    intro entry included
    exact valid_tree_has_prefix tree valid entry included _ (by dsimp [split]; omega)
  have route := joining_keys_have_opposite_routes (representative tree) digest
    (by simpa [difference_symmetric] using positive)
  rw [difference_symmetric (representative tree) digest] at route
  change (if representative tree < digest then _ else _) at route
  unfold join
  split
  next ordered =>
    simp only [ordered, ↓reduceIte] at route
    refine ⟨valid, by simp [Valid], positive, above,
      by simp [rank]; omega, ?_, ?_, ?_, ?_⟩
    · intro entry included
      rcases List.mem_append.mp included with old | fresh
      · exact oldPrefix entry old
      · have equal : entry = (digest, payload) := by simpa [entries] using fresh
        subst entry
        exact newPrefix
    · intro entry included
      exact (oldBits entry included).trans route.1
    · intro entry included
      have equal : entry = (digest, payload) := by simpa [entries] using included
      subst entry
      exact route.2
    · exact ⟨witness, List.mem_append_left _ member, same⟩
  next ordered =>
    simp only [ordered, ↓reduceIte] at route
    refine ⟨by simp [Valid], valid, positive,
      by simp [rank]; omega, above, ?_, ?_, ?_, ?_⟩
    · intro entry included
      rcases List.mem_append.mp included with fresh | old
      · have equal : entry = (digest, payload) := by simpa [entries] using fresh
        subst entry
        exact newPrefix
      · exact oldPrefix entry old
    · intro entry included
      have equal : entry = (digest, payload) := by simpa [entries] using included
      subst entry
      exact route.2
    · intro entry included
      exact (oldBits entry included).trans route.1
    · exact ⟨witness, List.mem_append_right _ member, same⟩

theorem child_difference_below_split (child : Tree) (old split digest : Nat)
    (side : Bool)
    (valid : Valid child) (positive : 0 < split)
    (commonPrefix : ∀ entry ∈ entries child, Above entry.1 old split)
    (route : ∀ entry ∈ entries child, entry.1.testBit (split - 1) = side)
    (newPrefix : Above digest old split)
    (newRoute : digest.testBit (split - 1) = side) :
    difference digest (representative child) < split := by
  obtain ⟨witness, present, same⟩ := representative_has_entry child valid
  have oldPrefix : Above (representative child) old split := by
    simpa [same] using commonPrefix witness present
  have oldRoute : (representative child).testBit (split - 1) = side := by
    simpa [same] using route witness present
  have combined := prefix_transitive _ _ _ _ newPrefix
    (prefix_symmetric _ _ _ oldPrefix)
  have narrow : Above digest (representative child) (split - 1) := by
    intro index included
    by_cases equal : index = split - 1
    · subst index
      exact newRoute.trans oldRoute.symm
    · exact combined index (by omega)
  have bounded := (difference_bounded_iff_prefix _ _ _).mpr narrow
  omega

theorem replace_left_preserves_validity (old split digest payload : Nat)
    (smaller larger : Tree) (valid : Valid (.branch old split smaller larger))
    (nextValid : Valid (insert smaller digest payload))
    (nextRank : rank (insert smaller digest payload) < split)
    (newPrefix : Above digest old split)
    (newRoute : digest.testBit (split - 1) = false) :
    Valid (.branch old split (insert smaller digest payload) larger) := by
  obtain ⟨_, large, positive, _, largeRank, commonPrefix,
    low, high, witness, present, same⟩ := valid
  refine ⟨nextValid, large, positive, nextRank, largeRank, ?_, ?_, high, ?_⟩
  · intro entry included
    rcases List.mem_append.mp included with left | right
    · rcases (insertion_preserves_exact_entries smaller digest payload entry).mp
        left with
        oldEntry | fresh
      · exact commonPrefix entry (List.mem_append_left _ oldEntry)
      · subst entry; exact newPrefix
    · exact commonPrefix entry (List.mem_append_right _ right)
  · intro entry included
    rcases (insertion_preserves_exact_entries smaller digest payload entry).mp
      included with
      oldEntry | fresh
    · exact low entry oldEntry
    · subst entry; exact newRoute
  · refine ⟨witness, ?_, same⟩
    rcases List.mem_append.mp present with left | right
    · exact List.mem_append_left _
        ((insertion_preserves_exact_entries _ _ _ _).mpr (Or.inl left))
    · exact List.mem_append_right _ right

theorem replace_right_preserves_validity (old split digest payload : Nat)
    (smaller larger : Tree) (valid : Valid (.branch old split smaller larger))
    (nextValid : Valid (insert larger digest payload))
    (nextRank : rank (insert larger digest payload) < split)
    (newPrefix : Above digest old split)
    (newRoute : digest.testBit (split - 1) = true) :
    Valid (.branch old split smaller (insert larger digest payload)) := by
  obtain ⟨small, _, positive, smallRank, _, commonPrefix,
    low, high, witness, present, same⟩ := valid
  refine ⟨small, nextValid, positive, smallRank, nextRank, ?_, low, ?_, ?_⟩
  · intro entry included
    rcases List.mem_append.mp included with left | right
    · exact commonPrefix entry (List.mem_append_left _ left)
    · rcases (insertion_preserves_exact_entries larger digest payload entry).mp
        right with
        oldEntry | fresh
      · exact commonPrefix entry (List.mem_append_right _ oldEntry)
      · subst entry; exact newPrefix
  · intro entry included
    rcases (insertion_preserves_exact_entries larger digest payload entry).mp
      included with
      oldEntry | fresh
    · exact high entry oldEntry
    · subst entry; exact newRoute
  · refine ⟨witness, ?_, same⟩
    rcases List.mem_append.mp present with left | right
    · exact List.mem_append_left _ left
    · exact List.mem_append_right _
        ((insertion_preserves_exact_entries _ _ _ _).mpr (Or.inl right))

theorem insertion_preserves_validity (tree : Tree) (digest payload : Nat)
    (valid : Valid tree) : Valid (insert tree digest payload) := by
  induction tree with
  | leaf old payloads =>
    by_cases same : difference digest old = 0
    · by_cases present : payload ∈ payloads
      · simpa [insert, representative, same, present] using valid
      · simp [insert, representative, same, present, Valid]
    · have above : rank (.leaf old payloads) < difference digest old := by
        simp only [rank]; omega
      simpa only [insert, representative, same, ↓reduceIte] using
        join_preserves_validity (.leaf old payloads) digest payload valid above
  | branch old split smaller larger left right =>
    by_cases above : split < difference digest old
    · simpa only [insert, representative, above, ↓reduceIte] using
        join_preserves_validity (.branch old split smaller larger)
          digest payload valid above
    · have newPrefix : Above digest old split :=
        (difference_bounded_iff_prefix digest old split).mp (by omega)
      have validBranch := valid
      obtain ⟨small, large, positive, smallRank, largeRank,
        commonPrefix, low, high, _⟩ := valid
      cases bit : digest.testBit (split - 1)
      · have below := child_difference_below_split smaller old split digest false
          small positive
          (fun entry present => commonPrefix entry (List.mem_append_left _ present))
          low newPrefix bit
        have bounded : rank (insert smaller digest payload) < split := by
          rw [insertion_rank]
          omega
        simpa only [insert, representative, above, ↓reduceIte, bit, Bool.false_eq_true]
          using replace_left_preserves_validity old split digest payload smaller larger
            validBranch (left small) bounded newPrefix bit
      · have below := child_difference_below_split larger old split digest true
          large positive
          (fun entry present => commonPrefix entry (List.mem_append_right _ present))
          high newPrefix bit
        have bounded : rank (insert larger digest payload) < split := by
          rw [insertion_rank]
          omega
        simpa only [insert, representative, above, ↓reduceIte, bit] using
          replace_right_preserves_validity old split digest payload smaller larger
            validBranch (right large) bounded newPrefix bit

theorem insertion_lookup_refines_map (tree : Tree) (digest payload query value : Nat)
    (valid : Valid tree) :
    value ∈ lookup (insert tree digest payload) query ↔
      value ∈ lookup tree query ∨ (query, value) = (digest, payload) :=
  routed_insertion_refines_map tree digest payload (valid_tree_routes tree valid)
    (valid_tree_routes _ (insertion_preserves_validity tree digest payload valid))
    query value

theorem history_preserves_validity (tree : Tree) (history : List Entry)
    (valid : Valid tree) :
    Valid (history.foldl (fun current entry => insert current entry.1 entry.2)
      tree) := by
  induction history generalizing tree with
  | nil => exact valid
  | cons first rest induction =>
    exact induction _ (insertion_preserves_validity tree first.1 first.2 valid)

theorem every_built_tree_is_valid (first : Entry) (rest : List Entry) :
    Valid (build first rest) :=
  history_preserves_validity _ _ (by simp [Valid])

theorem reachable_lookup_agrees_with_finite_map (first : Entry) (rest : List Entry)
    (digest payload : Nat) : payload ∈ lookup (build first rest) digest ↔
      (digest, payload) ∈ first :: rest := by
  rw [lookup_is_exact_leaf_map _
      (valid_tree_routes _ (every_built_tree_is_valid first rest)),
    build_agrees_with_finite_map]

theorem bounded_keys_have_bounded_difference (first second width : Nat)
    (one : first < 2 ^ width) (two : second < 2 ^ width) :
    difference first second ≤ width := by
  have bounded := Nat.xor_lt_two_pow one two
  by_cases zero : first ^^^ second = 0
  · simp [difference, zero]
  · have below := (Nat.log2_lt zero).mpr bounded
    simp only [difference, zero, ↓reduceIte]
    omega

theorem insertion_preserves_width (tree : Tree) (digest payload width : Nat)
    (rankBound : rank tree ≤ width) (old : representative tree < 2 ^ width)
    (fresh : digest < 2 ^ width) : rank (insert tree digest payload) ≤ width := by
  have bound := bounded_keys_have_bounded_difference digest (representative tree) width
    fresh old
  rw [insertion_rank]
  omega

theorem history_preserves_width (tree : Tree) (history : List Entry) (width : Nat)
    (rankBound : rank tree ≤ width) (old : representative tree < 2 ^ width)
    (bounded : ∀ entry ∈ history, entry.1 < 2 ^ width) :
    rank (history.foldl (fun current entry => insert current entry.1 entry.2) tree) ≤
      width := by
  induction history generalizing tree with
  | nil => exact rankBound
  | cons first rest induction =>
    apply induction
    · exact insertion_preserves_width tree first.1 first.2 width rankBound old
        (bounded first (by simp))
    · simpa [insertion_keeps_representative] using old
    · intro entry present
      exact bounded entry (by simp [present])

theorem every_insertion_order_has_bounded_depth (first : Entry) (rest : List Entry)
    (width : Nat) (bounded : ∀ entry ∈ first :: rest, entry.1 < 2 ^ width) :
    height (build first rest) ≤ width + 1 := by
  have rankBound : rank (build first rest) ≤ width :=
    history_preserves_width _ rest width (by simp [rank]) (bounded first (by simp))
      (fun entry present => bounded entry (by simp [present]))
  exact depth_bounded_by_digest_width _ width
    (valid_tree_descends _ (every_built_tree_is_valid first rest) width rankBound)

theorem reachable_lookup_order_independent (initial : Entry) (first second : List Entry)
    (same : ∀ entry, entry ∈ first ↔ entry ∈ second) (digest payload : Nat) :
    payload ∈ lookup (build initial first) digest ↔
      payload ∈ lookup (build initial second) digest := by
  simp only [reachable_lookup_agrees_with_finite_map, List.mem_cons, same]

end PeriScribe.GeometrySharing
