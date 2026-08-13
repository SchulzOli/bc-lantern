from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class IncrementalPlan:
    changed: tuple[str, ...]
    unchanged: tuple[str, ...]
    removed: tuple[str, ...]


def plan_incremental(
    current: Mapping[str, str],
    cached: Mapping[str, str],
    *,
    force: bool = False,
) -> IncrementalPlan:
    current_keys = set(current)
    cached_keys = set(cached)
    if force:
        changed = current_keys
        unchanged: set[str] = set()
    else:
        unchanged = {
            key
            for key in current_keys & cached_keys
            if current[key] == cached[key]
        }
        changed = current_keys - unchanged
    return IncrementalPlan(
        changed=tuple(sorted(changed)),
        unchanged=tuple(sorted(unchanged)),
        removed=tuple(sorted(cached_keys - current_keys)),
    )
