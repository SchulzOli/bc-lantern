from __future__ import annotations

from bccli.incremental import plan_incremental


def test_plan_incremental_splits_changed_unchanged_and_removed_items() -> None:
    plan = plan_incremental(
        current={"one": "same", "two": "new", "three": "first"},
        cached={"one": "same", "two": "old", "gone": "old"},
    )

    assert plan.unchanged == ("one",)
    assert plan.changed == ("three", "two")
    assert plan.removed == ("gone",)


def test_plan_incremental_force_marks_every_current_item_changed() -> None:
    plan = plan_incremental(
        current={"one": "same"}, cached={"one": "same"}, force=True
    )

    assert plan.changed == ("one",)
    assert plan.unchanged == ()
