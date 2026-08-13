from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from bc_lantern.object_ranges import (
    Interval,
    ObjectRangeDataError,
    _merge_intervals,
    _split_by_range_type,
    _subtract_interval,
    create_object_range_report,
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_report_rejects_negative_object_ids(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {"app_json": {"idRanges": [{"from": -1, "to": 1}]}}
            ],
        },
    )
    write_json(reference, {})

    with pytest.raises(ObjectRangeDataError, match="must be non-negative"):
        create_object_range_report(manifests, reference, output)


def test_high_unclassified_interval_stays_one_segment() -> None:
    start = 2**63
    assert _split_by_range_type(Interval(start, start + 2)) == [
        (Interval(start, start + 2), "unclassified")
    ]


def test_hidden_type_hides_restricted_table_use_details(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(manifests, {"schema_version": 1, "manifests": []})
    write_json(
        reference,
        {
            "Team": {
                "ranges": [{"from": 10, "to": 20}],
                "restricted_table_use": [{"from": 12, "to": 13}],
            }
        },
    )

    create_object_range_report(
        manifests, reference, output, hidden_range_types={"base"}
    )
    group = json.loads(output.read_text(encoding="utf-8"))["groups"][0]

    assert group["allocations"] == []
    assert group["restricted_table_use"] == []


def test_customization_ranges_are_not_conflicts_by_default(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {
                        "id": "a",
                        "name": "A",
                        "idRanges": [{"from": 50000, "to": 50010}],
                    },
                },
                {
                    "repository": "acme/b",
                    "path": "app.json",
                    "app_json": {
                        "id": "b",
                        "name": "B",
                        "idRanges": [{"from": 50005, "to": 50015}],
                    },
                },
            ],
        },
    )
    write_json(reference, {"Tests": {"ranges": [{"from": 50000, "to": 50015}]}})

    result = create_object_range_report(manifests, reference, output)
    report = json.loads(output.read_text(encoding="utf-8"))

    assert result.reserved_numbers == 16
    assert result.unreserved_numbers == 0
    assert result.conflicts == 0
    assert report["summary"]["conflicts"] == 0
    assert report["conflicts"] == []
    assert "customization" not in report["filters"]["conflict_range_types"]


def test_customization_conflicts_can_be_enabled_explicitly(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {
                        "id": "a",
                        "idRanges": [{"from": 50000, "to": 50010}],
                    },
                },
                {
                    "repository": "acme/b",
                    "path": "app.json",
                    "app_json": {
                        "id": "b",
                        "idRanges": [{"from": 50005, "to": 50015}],
                    },
                },
            ],
        },
    )
    write_json(reference, {"Tests": {"ranges": [{"from": 50000, "to": 50015}]}})

    result = create_object_range_report(
        manifests,
        reference,
        output,
        conflict_range_types={"customization"},
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert result.conflicts == 1
    assert report["filters"]["conflict_range_types"] == ["customization"]
    assert report["conflicts"][0]["from"] == 50005
    assert report["conflicts"][0]["to"] == 50010


def test_distinct_manifest_records_without_metadata_conflict(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {"app_json": {"idRanges": [{"from": 10, "to": 12}]}},
                {"app_json": {"idRanges": [{"from": 11, "to": 13}]}},
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 10, "to": 13}]}})

    create_object_range_report(manifests, reference, output)
    report = json.loads(output.read_text(encoding="utf-8"))

    assert report["summary"]["conflicts"] == 1
    assert report["conflicts"][0]["from"] == 11
    assert report["conflicts"][0]["to"] == 12
    assert len(report["conflicts"][0]["sources"]) == 2


def test_inclusive_subtraction_matches_finite_set_oracle() -> None:
    generator = random.Random(20260812)
    for _ in range(1000):
        start, end = sorted((generator.randint(-10, 60), generator.randint(-10, 60)))
        allocation = Interval(start, end)
        occupied = []
        for _ in range(generator.randint(0, 8)):
            used_start, used_end = sorted(
                (generator.randint(-20, 70), generator.randint(-20, 70))
            )
            occupied.append(Interval(used_start, used_end))

        actual = {
            number
            for interval in _subtract_interval(
                allocation, _merge_intervals(occupied)
            )
            for number in range(interval.start, interval.end + 1)
        }
        expected = set(range(start, end + 1)) - {
            number
            for interval in occupied
            for number in range(interval.start, interval.end + 1)
        }

        assert actual == expected


def test_report_subtracts_used_ranges_and_attributes_them_to_apps(
    tmp_path: Path,
) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "object_ranges.json"
    output = tmp_path / "object-range-report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "owner": "acme",
            "include_archived": False,
            "manifests": [
                {
                    "repository": "acme/first",
                    "path": "app.json",
                    "app_json": {
                        "id": "first-id",
                        "name": "First",
                        "publisher": "ACME",
                        "version": "1.0.0.0",
                        "objectRanges": [{"from": 1002, "to": 1004}],
                    },
                },
                {
                    "repository": "acme/second",
                    "path": "test/app.json",
                    "app_json": {
                        "id": "second-id",
                        "name": "Second",
                        "publisher": "ACME",
                        "version": "2.0.0.0",
                        "objectRanges": [{"from": 1007, "to": 1008}],
                    },
                },
            ],
        },
    )
    write_json(
        reference,
        {
            "Team A": {
                "ranges": [{"from": 1000, "to": 1009}],
                "restricted_table_use": [{"from": 1005, "to": 1005}],
            }
        },
    )

    result = create_object_range_report(manifests, reference, output)

    output_text = output.read_text(encoding="utf-8")
    report = json.loads(output_text)
    allocation = report["groups"][0]["allocations"][0]
    assert list(allocation)[:3] == ["from", "to", "size"]

    assert result.reference_ranges == 1
    assert result.declared_ranges == 2
    assert result.unreserved_ranges == 3
    assert result.reserved_numbers == 5
    assert result.unreserved_numbers == 5
    report = json.loads(output.read_text(encoding="utf-8"))
    allocation = report["groups"][0]["allocations"][0]
    assert allocation["unreserved_ranges"] == [
        {"from": 1000, "to": 1001, "size": 2},
        {"from": 1005, "to": 1006, "size": 2},
        {"from": 1009, "to": 1009, "size": 1},
    ]
    assert allocation["reserved_count"] == 5
    assert allocation["unreserved_count"] == 5
    assert allocation["reservations"] == [
        {
            "from": 1002,
            "to": 1004,
            "size": 3,
            "range_type": "base",
            "source": {
                "repository": "acme/first",
                "manifest_path": "app.json",
                "app_id": "first-id",
                "app_name": "First",
                "publisher": "ACME",
                "version": "1.0.0.0",
                "manifest_index": 0,
                "source_field": "objectRanges",
                "declared_from": 1002,
                "declared_to": 1004,
            },
        },
        {
            "from": 1007,
            "to": 1008,
            "size": 2,
            "range_type": "base",
            "source": {
                "repository": "acme/second",
                "manifest_path": "test/app.json",
                "app_id": "second-id",
                "app_name": "Second",
                "publisher": "ACME",
                "version": "2.0.0.0",
                "manifest_index": 1,
                "source_field": "objectRanges",
                "declared_from": 1007,
                "declared_to": 1008,
            },
        },
    ]
    assert report["groups"][0]["restricted_table_use"] == [
        {"from": 1005, "to": 1005, "size": 1}
    ]


def test_overlapping_declarations_from_one_manifest_are_not_cross_app_conflicts(
    tmp_path: Path,
) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {
                        "id": "a",
                        "idRanges": [
                            {"from": 10, "to": 15},
                            {"from": 14, "to": 20},
                        ],
                    },
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 10, "to": 20}]}})

    result = create_object_range_report(manifests, reference, output)

    assert result.conflicts == 0


def test_report_finds_conflicts_and_ranges_outside_reference(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "object_ranges.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {
                        "name": "A",
                        "objectRanges": [{"from": 10, "to": 15}],
                    },
                },
                {
                    "repository": "acme/b",
                    "path": "app.json",
                    "app_json": {
                        "name": "B",
                        "objectRanges": [{"from": 14, "to": 20}],
                    },
                },
                {
                    "repository": "acme/c",
                    "path": "app.json",
                    "app_json": {
                        "name": "C",
                        "objectRanges": [{"from": 30, "to": 31}],
                    },
                },
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 10, "to": 20}]}})

    create_object_range_report(manifests, reference, output)
    report = json.loads(output.read_text(encoding="utf-8"))

    assert report["conflicts"] == [
        {
            "from": 14,
            "to": 15,
            "size": 2,
            "range_type": "base",
            "sources": [
                {
                    "repository": "acme/a",
                    "manifest_path": "app.json",
                    "app_name": "A",
                    "manifest_index": 0,
                    "source_field": "objectRanges",
                    "declared_from": 10,
                    "declared_to": 15,
                },
                {
                    "repository": "acme/b",
                    "manifest_path": "app.json",
                    "app_name": "B",
                    "manifest_index": 1,
                    "source_field": "objectRanges",
                    "declared_from": 14,
                    "declared_to": 20,
                },
            ],
        }
    ]
    assert report["outside_reference"] == [
        {
            "from": 30,
            "to": 31,
            "size": 2,
            "range_type": "base",
            "source": {
                "repository": "acme/c",
                "manifest_path": "app.json",
                "app_name": "C",
                "manifest_index": 2,
                "source_field": "objectRanges",
                "declared_from": 30,
                "declared_to": 31,
            },
        }
    ]


def test_declared_range_count_is_not_inflated_by_type_splitting(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {"idRanges": [{"from": 49999, "to": 50001}]},
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 50000, "to": 50001}]}})

    result = create_object_range_report(manifests, reference, output)
    report = json.loads(output.read_text(encoding="utf-8"))

    assert result.declared_ranges == 1
    assert report["summary"]["declared_ranges"] == 1
    assert report["summary"]["typed_declared_segments"] == 2
    assert report["summary"]["outside_declarations"] == 1
    assert report["summary"]["outside_reference"] == 1


def test_report_classifies_and_splits_microsoft_range_types(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {
                        "name": "A",
                        "idRanges": [{"from": 49999, "to": 50001}],
                    },
                }
            ],
        },
    )
    write_json(
        reference,
        {"Team": {"ranges": [{"from": 49998, "to": 50002}]}},
    )

    create_object_range_report(manifests, reference, output)
    report = json.loads(output.read_text(encoding="utf-8"))
    allocations = report["groups"][0]["allocations"]
    reservations = [item for allocation in allocations for item in allocation["reservations"]]

    assert report["summary"]["reference_ranges"] == 1
    assert report["summary"]["typed_reference_segments"] == 2
    assert [allocation["range_type"] for allocation in allocations] == [
        "base",
        "customization",
    ]
    assert [
        (item["from"], item["to"], item["range_type"])
        for item in reservations
    ] == [
        (49999, 49999, "base"),
        (50000, 50001, "customization"),
    ]


def test_hidden_range_type_occupies_numbers_but_hides_use_details(
    tmp_path: Path,
) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {"idRanges": [{"from": 49999, "to": 50001}]},
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 49998, "to": 50002}]}})

    result = create_object_range_report(
        manifests, reference, output, hidden_range_types={"base"}
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    allocation = report["groups"][0]["allocations"][0]

    assert result.reserved_numbers == 3
    assert result.unreserved_numbers == 2
    assert [item["range_type"] for item in allocation["reservations"]] == [
        "customization"
    ]
    assert report["filters"] == {
        "hidden_range_types": ["base"],
        "ignored_range_types": [],
        "conflict_range_types": [
            "app",
            "base",
            "localization",
            "rsp",
            "unclassified",
        ],
    }


def test_hidden_type_hides_findings_but_preserves_summary_counts(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {"idRanges": [{"from": 10, "to": 12}]},
                },
                {
                    "repository": "acme/b",
                    "path": "app.json",
                    "app_json": {"idRanges": [{"from": 11, "to": 13}]},
                },
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 10, "to": 11}]}})

    result = create_object_range_report(
        manifests, reference, output, hidden_range_types={"base"}
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert result.conflicts == 1
    assert result.outside_declarations == 2
    assert result.outside_reference == 2
    assert report["summary"]["conflicts"] == 1
    assert report["summary"]["outside_declarations"] == 2
    assert report["summary"]["outside_reference"] == 2
    assert report["conflicts"] == []
    assert report["outside_reference"] == []


def test_ignored_customization_is_not_reported_outside_reference(
    tmp_path: Path,
) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/tests",
                    "path": "app.json",
                    "app_json": {
                        "id": "tests",
                        "idRanges": [{"from": 50000, "to": 99999}],
                    },
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 1000000, "to": 1000010}]}})

    result = create_object_range_report(
        manifests,
        reference,
        output,
        ignored_range_types={"customization"},
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert result.outside_declarations == 0
    assert result.outside_reference == 0
    assert report["summary"]["outside_declarations"] == 0
    assert report["summary"]["outside_reference"] == 0
    assert report["outside_reference"] == []


def test_ignored_type_is_removed_from_declaration_totals(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {"idRanges": [{"from": 49999, "to": 50001}]},
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 49999, "to": 50001}]}})

    result = create_object_range_report(
        manifests, reference, output, ignored_range_types={"base"}
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert result.declared_ranges == 1
    assert result.typed_declared_segments == 1
    assert report["summary"]["declared_ranges"] == 1
    assert report["summary"]["typed_declared_segments"] == 1


def test_ignored_range_type_does_not_occupy_numbers(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {"idRanges": [{"from": 49999, "to": 50001}]},
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 49998, "to": 50002}]}})

    result = create_object_range_report(
        manifests, reference, output, ignored_range_types={"base"}
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    allocations = report["groups"][0]["allocations"]
    allocation = allocations[0]

    assert result.reference_ranges == 1
    assert result.reserved_numbers == 2
    assert result.unreserved_numbers == 1
    assert allocation["range_type"] == "customization"
    assert allocation["from"] == 50000
    assert allocation["to"] == 50002
    assert allocation["unreserved_ranges"] == [
        {"from": 50002, "to": 50002, "size": 1},
    ]
    assert [item["range_type"] for item in allocation["reservations"]] == [
        "customization"
    ]


def test_id_ranges_precedence_ignores_different_legacy_ranges(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "app_json": {
                        "idRanges": [{"from": 10, "to": 12}],
                        "objectRanges": [{"from": 20, "to": 22}],
                    }
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 10, "to": 22}]}})

    create_object_range_report(manifests, reference, output)
    report = json.loads(output.read_text(encoding="utf-8"))

    assert report["summary"]["declared_ranges"] == 1
    assert report["summary"]["reserved_numbers"] == 3
    assert report["groups"][0]["allocations"][0]["reservations"][0]["to"] == 12


def test_malformed_selected_id_ranges_is_not_masked_by_legacy_field(
    tmp_path: Path,
) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "app_json": {
                        "idRanges": "invalid",
                        "objectRanges": [{"from": 20, "to": 22}],
                    }
                }
            ],
        },
    )
    write_json(reference, {})

    with pytest.raises(ObjectRangeDataError, match="idRanges must be an array"):
        create_object_range_report(manifests, reference, output)


def test_same_range_in_both_alias_fields_is_counted_once(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {
                        "id": "same-app",
                        "name": "A",
                        "idRanges": [{"from": 10, "to": 12}],
                        "objectRanges": [{"from": 10, "to": 12}],
                    },
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 10, "to": 12}]}})

    create_object_range_report(manifests, reference, output)
    report = json.loads(output.read_text(encoding="utf-8"))

    assert report["summary"]["declared_ranges"] == 1
    assert report["summary"]["reserved_numbers"] == 3
    assert len(report["groups"][0]["allocations"][0]["reservations"]) == 1


def test_report_accepts_business_central_id_ranges(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "object_ranges.json"
    output = tmp_path / "report.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {
                        "name": "A",
                        "idRanges": [{"from": 10, "to": 12}],
                    },
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 10, "to": 15}]}})

    result = create_object_range_report(manifests, reference, output)

    assert result.declared_ranges == 1
    allocation = json.loads(output.read_text(encoding="utf-8"))["groups"][0][
        "allocations"
    ][0]
    assert allocation["reservations"][0]["source"]["app_name"] == "A"
    assert allocation["reservations"][0]["source"]["source_field"] == "idRanges"
    assert allocation["reservations"][0]["source"]["declared_from"] == 10
    assert allocation["reservations"][0]["source"]["declared_to"] == 12
    assert allocation["unreserved_ranges"] == [{"from": 13, "to": 15, "size": 3}]


def test_markdown_conflict_sources_are_numbered_and_readable(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.md"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "src/app.json",
                    "app_json": {
                        "id": "app-a",
                        "name": "App A",
                        "publisher": "ACME",
                        "version": "1.0.0.0",
                        "idRanges": [{"from": 1000000, "to": 1000010}],
                    },
                },
                {
                    "repository": "acme/b",
                    "path": "app.json",
                    "app_json": {
                        "id": "app-b",
                        "name": "App B",
                        "publisher": "ACME",
                        "version": "2.0.0.0",
                        "idRanges": [{"from": 1000005, "to": 1000015}],
                    },
                },
            ],
        },
    )
    write_json(
        reference,
        {"Team": {"ranges": [{"from": 1000000, "to": 1000015}]}},
    )

    create_object_range_report(
        manifests, reference, output, output_format="markdown"
    )
    document = output.read_text(encoding="utf-8")
    conflict_section = document.split("## Conflicts", 1)[1].split(
        "## Outside reference", 1
    )[0]

    assert "**1. App A** (v1.0.0.0)" in conflict_section
    assert "Repository: `acme/a`" in conflict_section
    assert "Manifest: `src/app.json`" in conflict_section
    assert "Declared: `1000000..1000010` (`idRanges`)" in conflict_section
    assert "App ID: `app-a`" in conflict_section
    assert "**2. App B** (v2.0.0.0)" in conflict_section
    assert "<br>" in conflict_section
    assert "manifest_index=" not in conflict_section
    assert "repository=" not in conflict_section


def test_markdown_outside_reference_source_is_readable(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.md"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/outside",
                    "path": "src/app.json",
                    "app_json": {
                        "id": "outside-app-id",
                        "name": "Outside App",
                        "publisher": "ACME",
                        "version": "3.0.0.0",
                        "idRanges": [{"from": 1000020, "to": 1000029}],
                    },
                }
            ],
        },
    )
    write_json(
        reference,
        {"Team": {"ranges": [{"from": 1000000, "to": 1000010}]}},
    )

    create_object_range_report(
        manifests, reference, output, output_format="markdown"
    )
    document = output.read_text(encoding="utf-8")
    outside_section = document.split("## Outside reference", 1)[1]

    assert "**Outside App** (v3.0.0.0)" in outside_section
    assert "Repository: `acme/outside`" in outside_section
    assert "Manifest: `src/app.json`" in outside_section
    assert "Declared: `1000020..1000029` (`idRanges`)" in outside_section
    assert "App ID: `outside-app-id`" in outside_section
    assert "<br>" in outside_section
    assert "**1. Outside App**" not in outside_section
    assert "manifest_index=" not in outside_section
    assert "repository=" not in outside_section


def test_report_can_write_markdown_output(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.md"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/app",
                    "path": "app.json",
                    "app_json": {
                        "id": "example-app-id",
                        "name": "Example",
                        "publisher": "Example Publisher",
                        "version": "1.2.3.4",
                        "idRanges": [{"from": 50000, "to": 50003}],
                    },
                }
            ],
        },
    )
    write_json(
        reference,
        {
            "Team": {
                "ranges": [{"from": 50000, "to": 50002}],
                "restricted_table_use": [{"from": 50001, "to": 50001}],
            }
        },
    )

    result = create_object_range_report(
        manifests, reference, output, output_format="markdown"
    )
    document = output.read_text(encoding="utf-8")

    assert result.reserved_numbers == 3
    assert document.startswith("# Business Central object-range report\n")
    assert "- Schema version: 4" in document
    assert "- Conflict range types: `app`, `base`, `localization`, `rsp`, `unclassified`" in document
    assert "## Range types" in document
    assert "| customization | 50000 | 99999 |" in document
    assert "| unclassified | 75000000 | — |" in document
    assert "| From | To | Size | Type | Reserved | Unreserved |" in document
    assert "| 50000 | 50002 | 3 | customization | 3 | 0 |" in document
    assert "acme/app" in document
    assert "example-app-id" in document
    assert "Example Publisher" in document
    assert "1.2.3.4" in document
    assert "## Restricted table use" in document
    assert "| Team | 50001 | 50001 | 1 |" in document
    assert not document.lstrip().startswith("{")


def test_report_rejects_unsupported_output_format(tmp_path: Path) -> None:
    with pytest.raises(ObjectRangeDataError, match="output format"):
        create_object_range_report(
            tmp_path / "missing.json",
            tmp_path / "missing-reference.json",
            tmp_path / "report.txt",
            output_format="text",
        )


def test_report_rejects_overlapping_reference_allocations(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    write_json(manifests, {"schema_version": 1, "manifests": []})
    write_json(
        reference,
        {
            "Team A": {"ranges": [{"from": 50000, "to": 50010}]},
            "Team B": {"ranges": [{"from": 50010, "to": 50020}]},
        },
    )

    with pytest.raises(ObjectRangeDataError, match="overlap"):
        create_object_range_report(manifests, reference, tmp_path / "report.json")


def test_report_allows_adjacent_reference_allocations(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    output = tmp_path / "report.json"
    write_json(manifests, {"schema_version": 1, "manifests": []})
    write_json(
        reference,
        {
            "Team A": {"ranges": [{"from": 50000, "to": 50010}]},
            "Team B": {"ranges": [{"from": 50011, "to": 50020}]},
        },
    )

    result = create_object_range_report(manifests, reference, output)

    assert result.unreserved_numbers == 21


def test_report_rejects_invalid_ranges(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "object_ranges.json"
    write_json(
        manifests,
        {
            "schema_version": 1,
            "manifests": [
                {
                    "repository": "acme/a",
                    "path": "app.json",
                    "app_json": {"objectRanges": [{"from": 20, "to": 10}]},
                }
            ],
        },
    )
    write_json(reference, {"Team": {"ranges": [{"from": 10, "to": 20}]}})

    with pytest.raises(ObjectRangeDataError, match="from.*greater than.*to"):
        create_object_range_report(manifests, reference, tmp_path / "report.json")
