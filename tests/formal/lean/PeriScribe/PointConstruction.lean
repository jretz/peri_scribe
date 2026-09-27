import PeriScribe.SpatialIndex

namespace PeriScribe.PointConstruction
open SpatialIndex

/-- Disk partition routing must be a function of tile identity alone. -/
def partition (point : Point) : Nat := tile point % 16

def bucket (points : List Point) (identifier : Nat) : List Point :=
  points.filter (fun point => partition point == identifier)

/-- Assemble a tile from the one partition that owns all of its records. -/
def buildTile (points : List Point) (identifier : Nat) : List Point :=
  (bucket points (identifier % 16)).filter (fun point => tile point == identifier)

def occupiedTiles (points : List Point) : List Nat := (points.map tile).eraseDups

theorem deduplicated_keys_unique (values : List Nat) : values.eraseDups.Nodup := by
  cases values with
  | nil => simp
  | cons first rest =>
    rw [List.eraseDups_cons]
    apply List.nodup_cons.mpr
    constructor
    · simp [List.mem_eraseDups]
    · exact deduplicated_keys_unique (rest.filter (fun value => !value == first))
termination_by values.length
decreasing_by
  have bound := List.length_filter_le (fun value => !value == first) rest
  simp only [List.length_cons]
  omega

theorem one_row_per_tile (points : List Point) : (occupiedTiles points).Nodup :=
  deduplicated_keys_unique _

theorem every_record_has_a_row (points : List Point) (point : Point)
    (present : point ∈ points) : tile point ∈ occupiedTiles points := by
  simp only [occupiedTiles, List.mem_eraseDups, List.mem_map]
  exact ⟨point, present, rfl⟩

theorem same_tile_same_partition (first second : Point)
    (same : tile first = tile second) :
    partition first = partition second := by simp [partition, same]

theorem partition_is_bounded (point : Point) : partition point < 16 :=
  Nat.mod_lt _ (by decide)

/-- List equality, rather than set equality, preserves repeated point records. -/
theorem built_tile_equals_exhaustive (points : List Point) (identifier : Nat) :
    buildTile points identifier =
      points.filter (fun point => tile point == identifier) := by
  unfold buildTile bucket
  rw [List.filter_filter]
  apply List.filter_congr
  intro point _
  by_cases same : tile point = identifier
  · simp [partition, same]
  · simp [same]

theorem partition_append (first second : List Point) (identifier : Nat) :
    bucket (first ++ second) identifier =
      bucket first identifier ++ bucket second identifier := by
  simp [bucket]

theorem construction_append (first second : List Point) (identifier : Nat) :
    buildTile (first ++ second) identifier =
      buildTile first identifier ++ buildTile second identifier := by
  simp [built_tile_equals_exhaustive]

theorem chunk_boundaries_irrelevant (chunks : List (List Point)) (identifier : Nat) :
    buildTile chunks.flatten identifier =
      (chunks.map (fun chunk => buildTile chunk identifier)).flatten := by
  induction chunks with
  | nil => simp [built_tile_equals_exhaustive]
  | cons first rest induction => simp [construction_append, induction]

theorem order_independent (first second : List Point) (identifier : Nat)
    (reordered : first.Perm second) :
    (buildTile first identifier).Perm (buildTile second identifier) := by
  simp only [built_tile_equals_exhaustive]
  exact reordered.filter _

theorem point_multiplicity_preserved (points : List Point) (point : Point) :
    (buildTile points (tile point)).count point = points.count point := by
  rw [built_tile_equals_exhaustive]
  simp

theorem duplicate_records_preserved (points : List Point) (point : Point) :
    (buildTile (point :: point :: points) (tile point)).count point =
      points.count point + 2 := by
  rw [point_multiplicity_preserved]
  simp [Nat.add_assoc]

theorem no_foreign_records (points : List Point) (identifier : Nat) (point : Point)
    (present : point ∈ buildTile points identifier) :
    point ∈ points ∧ tile point = identifier := by
  simpa [built_tile_equals_exhaustive] using present

theorem every_occupied_row_is_nonempty (points : List Point) (identifier : Nat)
    (occupied : identifier ∈ occupiedTiles points) :
    buildTile points identifier ≠ [] := by
  simp only [occupiedTiles, List.mem_eraseDups, List.mem_map] at occupied
  rcases occupied with ⟨point, present, same⟩
  have retained : point ∈ buildTile points identifier := by
    simp [built_tile_equals_exhaustive, present, same]
  intro empty
  simp [empty] at retained

end PeriScribe.PointConstruction
