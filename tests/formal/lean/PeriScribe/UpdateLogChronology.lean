import PeriScribe.UpdateViewer

namespace PeriScribe.UpdateLogChronology

open UpdateViewer

/-- A committed receipt denotes physical overlap, otherwise plain rows are later. -/
def monthRows (committed : Bool) (archive plain : List Row) : List Row :=
  if committed then archive else archive ++ plain

theorem committed_source_is_not_replayed (archive source : List Row) :
    monthRows true archive source = archive := rfl

theorem late_tail_preserves_occurrences (archive plain : List Row) :
    monthRows false archive plain = archive ++ plain := rfl

theorem uncommitted_archive_is_a_prefix (archive plain : List Row) :
    archive <+: monthRows false archive plain := by
  exact ⟨plain, rfl⟩

theorem late_tail_keeps_duplicate_occurrences (archive : List Row) (row : Row) :
    monthRows false (archive ++ [row]) [row] = archive ++ [row, row] := by
  simp [monthRows, List.append_assoc]

/-- TLC's coherent-selection invariant connects physical representation to chronology. -/
theorem coherent_month_refines_complete_history (projection : Projection)
    (now width : Int) (committed : Bool) (archive plain logical following : List Row)
    (coherent : monthRows committed archive plain = logical) :
    projectedSnapshot projection now width
        (monthRows committed archive plain ++ following) =
      projectedReference projection now width [] (chronological (logical ++ following)) := by
  rw [coherent]
  exact projected_snapshot_equals_complete_history_reference projection now width _

theorem committed_and_retired_source_have_same_snapshot (projection : Projection)
    (now width : Int) (archive source following : List Row) :
    projectedSnapshot projection now width (monthRows true archive source ++ following) =
      projectedSnapshot projection now width (monthRows false archive [] ++ following) := by
  simp [monthRows]

theorem latest_late_row_supplies_current_owner_baseline (projection : Projection)
    (archive plain : List Row) (late : Row) (owner : Key)
    (same : projectedIdentity projection late = owner) :
    projectedPrevious projection (monthRows false archive (plain ++ [late])) owner =
      some late.area := by
  simp only [monthRows, Bool.false_eq_true, ↓reduceIte, ← List.append_assoc]
  exact latest_merged_record_supplies_baseline projection (archive ++ plain) late owner same

theorem equal_time_occurrence_order_is_preserved (rows : List Row) (first second : Row)
    (sameTime : first.time = second.time) (ordered : [first, second].Sublist rows) :
    [first, second].Sublist (chronological rows) := by
  exact List.pair_sublist_mergeSort
    (by intro a b c left right; simp_all; omega)
    (by intro a b; simp; omega)
    (by simp [sameTime]) ordered

/-- An old same-second late tail must supply the baseline of a later visible update. -/
def historical (serial area : Nat) : Row :=
  ⟨serial, -100, some 0, 0, some (2, 0), area⟩

def current : Row := ⟨2, 0, some 0, 0, some (2, 0), 150⟩

theorem equal_time_history_preserves_later_baseline :
    projectedSnapshot (fun _ => none) 0 10
        (monthRows false [historical 0 100] [historical 1 200] ++ [current]) =
      [⟨current, (2, 0), some 200⟩] := by
  have ordered : [historical 0 100, historical 1 200, current].Pairwise
      (fun first second => decide (first.time ≤ second.time)) := by decide
  simp only [monthRows, Bool.false_eq_true, ↓reduceIte, List.cons_append,
    List.nil_append, projectedSnapshot, chronological, List.mergeSort_of_pairwise ordered]
  rfl

theorem reversed_equal_time_history_changes_the_baseline :
    projectedSnapshot (fun _ => none) 0 10
        ([historical 1 200, historical 0 100, current]) =
      [⟨current, (2, 0), some 100⟩] := by
  have ordered : [historical 1 200, historical 0 100, current].Pairwise
      (fun first second => decide (first.time ≤ second.time)) := by decide
  rw [projectedSnapshot, chronological, List.mergeSort_of_pairwise ordered]
  rfl

end PeriScribe.UpdateLogChronology
