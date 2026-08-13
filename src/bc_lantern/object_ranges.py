from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bc_lantern.json_io import write_json_atomic, write_text_atomic

REPORT_SCHEMA_VERSION = 4

RANGE_TYPE_BOUNDS = (
    ("base", 0, 49_999),
    ("customization", 50_000, 99_999),
    ("localization", 100_000, 999_999),
    ("rsp", 1_000_000, 69_999_999),
    ("app", 70_000_000, 74_999_999),
)
RANGE_TYPES = tuple(item[0] for item in RANGE_TYPE_BOUNDS) + ("unclassified",)
DEFAULT_CONFLICT_RANGE_TYPES = tuple(
    range_type for range_type in RANGE_TYPES if range_type != "customization"
)


class ObjectRangeDataError(ValueError):
    """Raised when manifest or reference range data has an invalid shape."""


@dataclass(frozen=True)
class Interval:
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class DeclaredRange:
    interval: Interval
    source: dict[str, Any]
    range_type: str
    declaration_id: int = 0
    manifest_id: int = 0


@dataclass(frozen=True)
class ObjectRangeReportResult:
    reference_ranges: int
    typed_reference_segments: int
    declared_ranges: int
    typed_declared_segments: int
    unreserved_ranges: int
    reserved_numbers: int
    unreserved_numbers: int
    conflicts: int
    outside_declarations: int
    outside_reference: int


def create_object_range_report(
    manifests_file: Path,
    reference_file: Path,
    output_file: Path,
    *,
    hidden_range_types: set[str] | None = None,
    ignored_range_types: set[str] | None = None,
    conflict_range_types: set[str] | None = None,
    output_format: str = "json",
) -> ObjectRangeReportResult:
    if output_format not in {"json", "markdown"}:
        raise ObjectRangeDataError(
            "output format must be one of: json, markdown"
        )
    hidden = _validate_range_types(hidden_range_types or set(), "hidden")
    ignored = _validate_range_types(ignored_range_types or set(), "ignored")
    conflict_types = _validate_range_types(
        set(DEFAULT_CONFLICT_RANGE_TYPES)
        if conflict_range_types is None
        else conflict_range_types,
        "conflict",
    )
    manifests_document = _read_json(manifests_file)
    reference_document = _read_json(reference_file)
    declared = _read_declared_ranges(manifests_document)
    effective_declared = [item for item in declared if item.range_type not in ignored]
    groups = _read_reference_groups(reference_document)
    _validate_non_overlapping_reference_groups(groups)
    reference_range_count = sum(
        1
        for _, allocations, _ in groups
        for allocation in allocations
        if any(
            range_type not in ignored
            for _, range_type in _split_by_range_type(allocation)
        )
    )
    effective_groups = []
    reference_intervals: list[Interval] = []
    for group_name, allocations, restricted in groups:
        typed_allocations = [
            (part, range_type)
            for allocation in allocations
            for part, range_type in _split_by_range_type(allocation)
            if range_type not in ignored
        ]
        effective_restricted = [
            (part, range_type)
            for interval in restricted
            for part, range_type in _split_by_range_type(interval)
            if range_type not in ignored
        ]
        reference_intervals.extend(part for part, _ in typed_allocations)
        effective_groups.append(
            (group_name, typed_allocations, effective_restricted)
        )

    report_groups: list[dict[str, Any]] = []
    unreserved_range_count = 0
    reserved_number_count = 0
    unreserved_number_count = 0
    typed_reference_segment_count = 0
    for group_name, typed_allocations, restricted in effective_groups:
        rendered_allocations = []
        for allocation, allocation_range_type in typed_allocations:
            typed_reference_segment_count += 1
            all_reservations = _reservations_in_allocation(effective_declared, allocation)
            visible_reservations = [
                item for item in all_reservations if item["range_type"] not in hidden
            ]
            occupied = _merge_intervals(
                Interval(item["from"], item["to"]) for item in all_reservations
            )
            free = _subtract_interval(allocation, occupied)
            reserved_count = sum(item.size for item in occupied)
            unreserved_count = sum(item.size for item in free)
            reserved_number_count += reserved_count
            unreserved_number_count += unreserved_count
            unreserved_range_count += len(free)
            if allocation_range_type not in hidden:
                rendered_allocations.append(
                    {
                        **_interval_json(allocation),
                        "range_type": allocation_range_type,
                        "reserved_count": reserved_count,
                        "unreserved_count": unreserved_count,
                        "reservations": visible_reservations,
                        "unreserved_ranges": [_interval_json(item) for item in free],
                    }
                )
        report_groups.append(
            {
                "name": group_name,
                "allocations": rendered_allocations,
                "restricted_table_use": [
                    _interval_json(item)
                    for item, range_type in restricted
                    if range_type not in hidden
                ],
            }
        )

    conflict_declared = [
        item for item in effective_declared if item.range_type in conflict_types
    ]
    all_conflicts = _find_conflicts(conflict_declared)
    conflicts = [
        item for item in all_conflicts if item["range_type"] not in hidden
    ]
    all_outside_reference = _find_outside_reference(
        effective_declared, reference_intervals
    )
    outside_declaration_count = len(
        {item["declaration_id"] for item in all_outside_reference}
    )
    outside_reference_count = len(all_outside_reference)
    outside_reference = [
        item
        for item in all_outside_reference
        if item["range_type"] not in hidden
    ]
    declared_range_count = len(
        {item.declaration_id for item in effective_declared}
    )
    for item in outside_reference:
        del item["declaration_id"]
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "source": {
            "app_json": str(manifests_file.resolve()),
            "reference": str(reference_file.resolve()),
        },
        "range_types": [
            {"name": name, "from": start, "to": end}
            for name, start, end in RANGE_TYPE_BOUNDS
        ]
        + [{"name": "unclassified", "from": 75_000_000, "to": None}],
        "filters": {
            "hidden_range_types": sorted(hidden),
            "ignored_range_types": sorted(ignored),
            "conflict_range_types": sorted(conflict_types),
        },
        "summary": {
            "reference_ranges": reference_range_count,
            "typed_reference_segments": typed_reference_segment_count,
            "declared_ranges": declared_range_count,
            "typed_declared_segments": len(effective_declared),
            "unreserved_ranges": unreserved_range_count,
            "reserved_numbers": reserved_number_count,
            "unreserved_numbers": unreserved_number_count,
            "conflicts": len(all_conflicts),
            "outside_declarations": outside_declaration_count,
            "outside_reference": outside_reference_count,
        },
        "groups": report_groups,
        "conflicts": conflicts,
        "outside_reference": outside_reference,
    }
    if output_format == "json":
        write_json_atomic(output_file, report, sort_keys=False)
    else:
        write_text_atomic(output_file, _render_markdown_report(report))
    return ObjectRangeReportResult(
        reference_ranges=reference_range_count,
        typed_reference_segments=typed_reference_segment_count,
        declared_ranges=declared_range_count,
        typed_declared_segments=len(effective_declared),
        unreserved_ranges=unreserved_range_count,
        reserved_numbers=reserved_number_count,
        unreserved_numbers=unreserved_number_count,
        conflicts=len(all_conflicts),
        outside_declarations=outside_declaration_count,
        outside_reference=outside_reference_count,
    )


def _render_markdown_report(report: dict[str, Any]) -> str:
    source = report["source"]
    filters = report["filters"]
    summary = report["summary"]
    lines = [
        "# Business Central object-range report",
        "",
        f"- Schema version: {report['schema_version']}",
        f"- App manifest source: `{_markdown_text(source['app_json'])}`",
        f"- Reference source: `{_markdown_text(source['reference'])}`",
        f"- Hidden range types: {_markdown_list(filters['hidden_range_types'])}",
        f"- Ignored range types: {_markdown_list(filters['ignored_range_types'])}",
        f"- Conflict range types: {_markdown_list(filters['conflict_range_types'])}",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    for key, label in (
        ("reference_ranges", "Reference ranges"),
        ("typed_reference_segments", "Typed reference segments"),
        ("declared_ranges", "Declared ranges"),
        ("typed_declared_segments", "Typed declared segments"),
        ("unreserved_ranges", "Unreserved ranges"),
        ("reserved_numbers", "Reserved object numbers"),
        ("unreserved_numbers", "Unreserved object numbers"),
        ("conflicts", "Conflicts"),
        ("outside_declarations", "Outside declarations"),
        ("outside_reference", "Outside-reference segments"),
    ):
        lines.append(f"| {label} | {summary[key]} |")

    lines.extend(
        [
            "",
            "## Range types",
            "",
            "| Type | From | To |",
            "|---|---:|---:|",
        ]
    )
    for range_type in report["range_types"]:
        start = "—" if range_type["from"] is None else range_type["from"]
        end = "—" if range_type["to"] is None else range_type["to"]
        lines.append(
            f"| {_markdown_text(range_type['name'])} | {start} | {end} |"
        )

    lines.extend(["", "## Allocations", ""])
    for group in report["groups"]:
        lines.extend(
            [
                f"### {_markdown_text(group['name'])}",
                "",
                "| From | To | Size | Type | Reserved | Unreserved |",
                "|---:|---:|---:|---|---:|---:|",
            ]
        )
        allocations = group["allocations"]
        if allocations:
            for allocation in allocations:
                lines.append(
                    "| {from_} | {to} | {size} | {type_} | {used} | {free} |".format(
                        from_=allocation["from"],
                        to=allocation["to"],
                        size=allocation["size"],
                        type_=_markdown_text(allocation["range_type"]),
                        used=allocation["reserved_count"],
                        free=allocation["unreserved_count"],
                    )
                )
        else:
            lines.append("| — | — | — | — | — | — |")

        reservations = [use for allocation in allocations for use in allocation["reservations"]]
        lines.extend(
            [
                "",
                "#### Reservations",
                "",
                "| From | To | Size | Type | Record | Repository | Manifest | App ID | App | Publisher | Version | Source field | Declared from | Declared to |",
                "|---:|---:|---:|---|---:|---|---|---|---|---|---|---|---:|---:|",
            ]
        )
        if reservations:
            for use in reservations:
                lines.append(_markdown_use_row(use))
        else:
            lines.append("| — | — | — | — | — | — | — | — | — | — | — | — | — | — |")

        unreserved_ranges = [
            free_range
            for allocation in allocations
            for free_range in allocation["unreserved_ranges"]
        ]
        lines.extend(
            [
                "",
                "#### Unreserved ranges",
                "",
                "| From | To | Size |",
                "|---:|---:|---:|",
            ]
        )
        if unreserved_ranges:
            for free_range in unreserved_ranges:
                lines.append(
                    f"| {free_range['from']} | {free_range['to']} | {free_range['size']} |"
                )
        else:
            lines.append("| — | — | — |")
        lines.append("")

    lines.extend(
        [
            "## Restricted table use",
            "",
            "| Group | From | To | Size |",
            "|---|---:|---:|---:|",
        ]
    )
    restrictions = [
        (group["name"], interval)
        for group in report["groups"]
        for interval in group["restricted_table_use"]
    ]
    if restrictions:
        for group_name, interval in restrictions:
            lines.append(
                f"| {_markdown_text(group_name)} | {interval['from']} | "
                f"{interval['to']} | {interval['size']} |"
            )
    else:
        lines.append("| — | — | — | — |")

    lines.extend(_markdown_findings("Conflicts", report["conflicts"], conflicts=True))
    lines.extend(
        _markdown_findings(
            "Outside reference", report["outside_reference"], conflicts=False
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def _markdown_findings(
    title: str, findings: list[dict[str, Any]], *, conflicts: bool
) -> list[str]:
    source_heading = "Sources" if conflicts else "Source"
    lines = [
        "",
        f"## {title}",
        "",
        f"| From | To | Size | Type | {source_heading} |",
        "|---:|---:|---:|---|---|",
    ]
    if not findings:
        lines.append("| — | — | — | — | — |")
        return lines
    for finding in findings:
        sources = finding["sources"] if conflicts else [finding["source"]]
        if conflicts:
            source_text = "<br><br>".join(
                _markdown_finding_source(source, index)
                for index, source in enumerate(sources, start=1)
            )
        else:
            source_text = _markdown_finding_source(sources[0])
        lines.append(
            f"| {finding['from']} | {finding['to']} | {finding['size']} | "
            f"{_markdown_text(finding['range_type'])} | {source_text} |"
        )
    return lines


def _markdown_use_row(use: dict[str, Any]) -> str:
    source = use["source"]
    return (
        f"| {use['from']} | {use['to']} | {use['size']} | "
        f"{_markdown_text(use['range_type'])} | "
        f"{_markdown_text(source.get('manifest_index', ''))} | "
        f"{_markdown_text(source.get('repository', ''))} | "
        f"{_markdown_text(source.get('manifest_path', ''))} | "
        f"{_markdown_text(source.get('app_id', ''))} | "
        f"{_markdown_text(source.get('app_name', ''))} | "
        f"{_markdown_text(source.get('publisher', ''))} | "
        f"{_markdown_text(source.get('version', ''))} | "
        f"{_markdown_text(source.get('source_field', ''))} | "
        f"{_markdown_text(source.get('declared_from', ''))} | "
        f"{_markdown_text(source.get('declared_to', ''))} |"
    )


def _markdown_finding_source(
    source: dict[str, Any], index: int | None = None
) -> str:
    app_name = source.get("app_name") or "Unnamed app"
    version = source.get("version")
    prefix = f"{index}. " if index is not None else ""
    heading = f"**{prefix}{_markdown_text(app_name)}**"
    if version:
        heading += f" (v{_markdown_text(version)})"

    details = [heading]
    repository = source.get("repository")
    if repository:
        details.append(f"Repository: `{_markdown_code(repository)}`")
    manifest = source.get("manifest_path")
    if manifest:
        details.append(f"Manifest: `{_markdown_code(manifest)}`")

    declared_from = source.get("declared_from")
    declared_to = source.get("declared_to")
    source_field = source.get("source_field")
    if declared_from != "" and declared_to != "":
        declared = f"Declared: `{declared_from}..{declared_to}`"
        if source_field:
            declared += f" (`{_markdown_code(source_field)}`)"
        details.append(declared)

    app_id = source.get("app_id")
    if app_id:
        details.append(f"App ID: `{_markdown_code(app_id)}`")
    return "<br>".join(details)


def _markdown_code(value: Any) -> str:
    return _markdown_text(value).replace("`", "\\`")


def _markdown_list(values: list[str]) -> str:
    return ", ".join(f"`{_markdown_text(value)}`" for value in values) or "none"


def _markdown_text(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ObjectRangeDataError(
            f"Invalid JSON in {path}: {error.msg}"
        ) from error


def _read_declared_ranges(document: Any) -> list[DeclaredRange]:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ObjectRangeDataError("app-json input must use schema_version 1")
    manifests = document.get("manifests")
    if not isinstance(manifests, list):
        raise ObjectRangeDataError("app-json input must contain a manifests array")

    declared: list[DeclaredRange] = []
    declaration_id = 0
    for manifest_index, manifest in enumerate(manifests):
        context = f"manifests[{manifest_index}]"
        if not isinstance(manifest, dict):
            raise ObjectRangeDataError(f"{context} must be an object")
        app_json = manifest.get("app_json")
        if not isinstance(app_json, dict):
            raise ObjectRangeDataError(f"{context}.app_json must be an object")
        range_fields = []
        if "idRanges" in app_json:
            range_fields.append(("idRanges", app_json["idRanges"]))
        elif "objectRanges" in app_json:
            range_fields.append(("objectRanges", app_json["objectRanges"]))
        source = _source(manifest, app_json)
        for field_name, ranges in range_fields:
            if not isinstance(ranges, list):
                raise ObjectRangeDataError(
                    f"{context}.app_json.{field_name} must be an array"
                )
            for range_index, value in enumerate(ranges):
                interval = _parse_interval(
                    value,
                    f"{context}.app_json.{field_name}[{range_index}]",
                )
                declaration_source = {
                    **source,
                    "manifest_index": manifest_index,
                    "source_field": field_name,
                    "declared_from": interval.start,
                    "declared_to": interval.end,
                }
                declared.extend(
                    DeclaredRange(
                        part,
                        declaration_source,
                        range_type,
                        declaration_id,
                        manifest_index,
                    )
                    for part, range_type in _split_by_range_type(interval)
                )
                declaration_id += 1
    return sorted(
        declared,
        key=lambda item: (
            item.interval.start,
            item.interval.end,
            item.source.get("repository", ""),
            item.source.get("manifest_path", ""),
        ),
    )


def _source(manifest: dict[str, Any], app_json: dict[str, Any]) -> dict[str, str]:
    candidates = (
        ("repository", manifest.get("repository")),
        ("manifest_path", manifest.get("path")),
        ("app_id", app_json.get("id")),
        ("app_name", app_json.get("name")),
        ("publisher", app_json.get("publisher")),
        ("version", app_json.get("version")),
    )
    return {key: value for key, value in candidates if isinstance(value, str)}


def _validate_non_overlapping_reference_groups(
    groups: list[tuple[str, list[Interval], list[Interval]]],
) -> None:
    allocations = sorted(
        (interval.start, interval.end, group_name)
        for group_name, ranges, _ in groups
        for interval in ranges
    )
    for previous, current in zip(allocations, allocations[1:]):
        if current[0] <= previous[1]:
            raise ObjectRangeDataError(
                "reference allocations overlap: "
                f"{previous[2]} {previous[0]}..{previous[1]} and "
                f"{current[2]} {current[0]}..{current[1]}"
            )


def _read_reference_groups(
    document: Any,
) -> list[tuple[str, list[Interval], list[Interval]]]:
    if not isinstance(document, dict):
        raise ObjectRangeDataError("reference input must be a JSON object")
    groups = []
    for group_name, value in document.items():
        if not isinstance(group_name, str) or not isinstance(value, dict):
            raise ObjectRangeDataError("each reference group must be an object")
        ranges = _parse_interval_array(value.get("ranges"), f"{group_name}.ranges")
        restricted = _parse_interval_array(
            value.get("restricted_table_use", []),
            f"{group_name}.restricted_table_use",
        )
        groups.append((group_name, ranges, restricted))
    return groups


def _parse_interval_array(value: Any, context: str) -> list[Interval]:
    if not isinstance(value, list):
        raise ObjectRangeDataError(f"{context} must be an array")
    return [_parse_interval(item, f"{context}[{index}]") for index, item in enumerate(value)]


def _parse_interval(value: Any, context: str) -> Interval:
    if not isinstance(value, dict):
        raise ObjectRangeDataError(f"{context} must be an object")
    start = value.get("from")
    end = value.get("to")
    if isinstance(start, bool) or not isinstance(start, int):
        raise ObjectRangeDataError(f"{context}.from must be an integer")
    if isinstance(end, bool) or not isinstance(end, int):
        raise ObjectRangeDataError(f"{context}.to must be an integer")
    if start < 0 or end < 0:
        raise ObjectRangeDataError(f"{context} bounds must be non-negative")
    if start > end:
        raise ObjectRangeDataError(
            f"{context}.from ({start}) is greater than .to ({end})"
        )
    return Interval(start, end)


def _split_by_range_type(interval: Interval) -> list[tuple[Interval, str]]:
    parts: list[tuple[Interval, str]] = []
    cursor = interval.start
    while cursor <= interval.end:
        range_type, type_end = _range_type_at(cursor)
        end = interval.end if type_end is None else min(interval.end, type_end)
        parts.append((Interval(cursor, end), range_type))
        cursor = end + 1
    return parts


def _range_type_at(number: int) -> tuple[str, int | None]:
    for name, start, end in RANGE_TYPE_BOUNDS:
        if start <= number <= end:
            return name, end
        if number < start:
            return "unclassified", start - 1
    return "unclassified", None


def _validate_range_types(values: set[str], filter_name: str) -> set[str]:
    invalid = sorted(values - set(RANGE_TYPES))
    if invalid:
        raise ObjectRangeDataError(
            f"Unknown {filter_name} range type(s): {', '.join(invalid)}. "
            f"Valid types: {', '.join(RANGE_TYPES)}"
        )
    return set(values)


def _reservations_in_allocation(
    declared: list[DeclaredRange], allocation: Interval
) -> list[dict[str, Any]]:
    reservations = []
    for item in declared:
        intersection = _intersection(item.interval, allocation)
        if intersection is not None:
            reservations.append(
                {
                    **_interval_json(intersection),
                    "range_type": item.range_type,
                    "source": item.source,
                }
            )
    return reservations


def _intersection(left: Interval, right: Interval) -> Interval | None:
    start = max(left.start, right.start)
    end = min(left.end, right.end)
    return Interval(start, end) if start <= end else None


def _merge_intervals(intervals: Any) -> list[Interval]:
    ordered = sorted(intervals, key=lambda item: (item.start, item.end))
    merged: list[Interval] = []
    for interval in ordered:
        if not merged or interval.start > merged[-1].end + 1:
            merged.append(interval)
        else:
            merged[-1] = Interval(
                merged[-1].start, max(merged[-1].end, interval.end)
            )
    return merged


def _subtract_interval(
    allocation: Interval, occupied: list[Interval]
) -> list[Interval]:
    result = []
    cursor = allocation.start
    for used in occupied:
        clipped = _intersection(allocation, used)
        if clipped is None:
            continue
        if cursor < clipped.start:
            result.append(Interval(cursor, clipped.start - 1))
        cursor = max(cursor, clipped.end + 1)
    if cursor <= allocation.end:
        result.append(Interval(cursor, allocation.end))
    return result


def _subtract_many(interval: Interval, covered: list[Interval]) -> list[Interval]:
    remaining = [interval]
    for cover in covered:
        next_remaining = []
        for item in remaining:
            overlap = _intersection(item, cover)
            if overlap is None:
                next_remaining.append(item)
                continue
            if item.start < overlap.start:
                next_remaining.append(Interval(item.start, overlap.start - 1))
            if overlap.end < item.end:
                next_remaining.append(Interval(overlap.end + 1, item.end))
        remaining = next_remaining
    return remaining


def _find_outside_reference(
    declared: list[DeclaredRange], reference_intervals: list[Interval]
) -> list[dict[str, Any]]:
    result = []
    for item in declared:
        for interval in _subtract_many(item.interval, reference_intervals):
            result.append(
                {
                    **_interval_json(interval),
                    "range_type": item.range_type,
                    "declaration_id": item.declaration_id,
                    "source": item.source,
                }
            )
    return result


def _source_identity(item: DeclaredRange) -> tuple[str, ...]:
    app_id = item.source.get("app_id")
    if isinstance(app_id, str) and app_id:
        return ("app_id", app_id)
    return ("manifest", str(item.manifest_id))


def _find_conflicts(declared: list[DeclaredRange]) -> list[dict[str, Any]]:
    if len(declared) < 2:
        return []
    boundaries = sorted(
        {point for item in declared for point in (item.interval.start, item.interval.end + 1)}
    )
    segments: list[
        tuple[Interval, str, tuple[tuple[tuple[str, str], ...], ...]]
    ] = []
    source_lookup: dict[tuple[tuple[str, str], ...], dict[str, str]] = {}
    for start, stop in zip(boundaries, boundaries[1:]):
        active = []
        active_identities = set()
        active_type = "unclassified"
        for item in declared:
            if item.interval.start <= start <= item.interval.end:
                active_type = item.range_type
                key = tuple(item.source.items())
                source_lookup[key] = item.source
                if key not in active:
                    active.append(key)
                active_identities.add(_source_identity(item))
        if len(active_identities) >= 2:
            segments.append(
                (Interval(start, stop - 1), active_type, tuple(sorted(active)))
            )

    merged: list[
        tuple[Interval, str, tuple[tuple[tuple[str, str], ...], ...]]
    ] = []
    for interval, range_type, sources in segments:
        if (
            merged
            and merged[-1][1] == range_type
            and merged[-1][2] == sources
            and merged[-1][0].end + 1 == interval.start
        ):
            merged[-1] = (
                Interval(merged[-1][0].start, interval.end),
                range_type,
                sources,
            )
        else:
            merged.append((interval, range_type, sources))
    return [
        {
            **_interval_json(interval),
            "range_type": range_type,
            "sources": [source_lookup[source] for source in sources],
        }
        for interval, range_type, sources in merged
    ]


def _interval_json(interval: Interval) -> dict[str, int]:
    return {"from": interval.start, "to": interval.end, "size": interval.size}
