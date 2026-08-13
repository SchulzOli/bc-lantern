from __future__ import annotations

import json
from pathlib import Path

from bccli.cache import JsonCacheStore
from bccli.cli import main
from bccli.github import Repository, RepositoryFile


class RecordingClient:
    def __init__(self) -> None:
        self.include_archived: bool | None = None

    def authenticated_user(self) -> str:
        return "signed-in-user"

    def list_repositories(
        self, owner: str, *, include_archived: bool = False
    ) -> list[Repository]:
        assert owner == "signed-in-user"
        self.include_archived = include_archived
        return [Repository("signed-in-user/al-app", True, "main")]

    def find_app_json_files(self, repository: Repository) -> list[RepositoryFile]:
        return [RepositoryFile("app.json", "example-sha")]

    def get_file(self, repository: Repository, path: str) -> str:
        return '{"name": "Example"}'


def test_cli_retrieves_app_json_for_authenticated_user(
    tmp_path: Path, capsys: object
) -> None:
    client = RecordingClient()

    output_file = tmp_path / "app-json.json"
    exit_code = main(
        [
            "app-json",
            "retrieve",
            "--include-archived",
            "--no-cache",
            "--output",
            str(output_file),
        ],
        client=client,
    )

    assert exit_code == 0
    assert client.include_archived is True
    assert json.loads(output_file.read_text(encoding="utf-8"))["manifests"][0][
        "app_json"
    ] == {"name": "Example"}
    output = capsys.readouterr().out
    assert "Repositories scanned: 1" in output
    assert "AL repositories: 1" in output
    assert "app.json files downloaded: 1" in output


def test_cli_uses_injected_cache_and_reports_incremental_stats(
    tmp_path: Path, capsys: object
) -> None:
    client = RecordingClient()
    cache = JsonCacheStore(tmp_path / "cache")
    args = [
        "app-json",
        "retrieve",
        "--include-archived",
        "--output",
        str(tmp_path / "app-json.json"),
    ]

    assert main(args, client=client, cache=cache) == 0
    capsys.readouterr()
    assert main(args, client=client, cache=cache) == 0

    output = capsys.readouterr().out
    assert "Repositories updated: 0" in output
    assert "Repositories from cache: 1" in output
    assert "app.json files downloaded: 0" in output
    assert "app.json files unchanged: 1" in output


def test_cli_reports_missing_object_range_input_as_a_file_error(
    tmp_path: Path, capsys: object
) -> None:
    missing = tmp_path / "missing-app-json.json"
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({}), encoding="utf-8")

    exit_code = main(
        [
            "object-ranges",
            "report",
            "--app-json",
            str(missing),
            "--reference",
            str(reference),
            "--output",
            str(tmp_path / "report.json"),
        ]
    )

    assert exit_code == 1
    error = capsys.readouterr().err
    assert f"Input file not found: {missing}" in error
    assert "GitHub CLI" not in error


def test_cli_creates_object_range_report(tmp_path: Path, capsys: object) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    report = tmp_path / "report.json"
    manifests.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifests": [
                    {
                        "repository": "acme/app",
                        "path": "app.json",
                        "app_json": {
                            "name": "App",
                            "objectRanges": [{"from": 101, "to": 102}],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reference.write_text(
        json.dumps({"Team": {"ranges": [{"from": 100, "to": 103}]}}),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "object-ranges",
            "report",
            "--app-json",
            str(manifests),
            "--reference",
            str(reference),
            "--output",
            str(report),
        ]
    )

    assert exit_code == 0
    assert report.is_file()
    output = capsys.readouterr().out
    assert "Declared ranges: 1" in output
    assert "Unreserved ranges: 2" in output
    assert "Conflicts: 0" in output
    assert "Outside declarations: 0" in output
    assert "Outside-reference segments: 0" in output


def test_cli_writes_markdown_object_range_report(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    report = tmp_path / "report.md"
    manifests.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifests": [
                    {
                        "repository": "acme/app",
                        "path": "app.json",
                        "app_json": {"idRanges": [{"from": 50000, "to": 50000}]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reference.write_text(
        json.dumps({"Team": {"ranges": [{"from": 50000, "to": 50001}]}}),
        encoding="utf-8",
    )

    assert main(
        [
            "object-ranges",
            "report",
            "--app-json",
            str(manifests),
            "--reference",
            str(reference),
            "--output",
            str(report),
            "--output-format",
            "markdown",
        ]
    ) == 0
    assert report.read_text(encoding="utf-8").startswith(
        "# Business Central object-range report"
    )


def test_cli_can_enable_customization_conflicts(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    report = tmp_path / "report.json"
    manifests.write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )
    reference.write_text(
        json.dumps({"Tests": {"ranges": [{"from": 50000, "to": 50015}]}}),
        encoding="utf-8",
    )

    assert main(
        [
            "object-ranges",
            "report",
            "--app-json",
            str(manifests),
            "--reference",
            str(reference),
            "--output",
            str(report),
            "--conflict-range-type",
            "customization",
        ]
    ) == 0

    document = json.loads(report.read_text(encoding="utf-8"))
    assert document["filters"]["conflict_range_types"] == ["customization"]
    assert document["summary"]["conflicts"] == 1


def test_cli_filters_range_types(tmp_path: Path) -> None:
    manifests = tmp_path / "app-json.json"
    reference = tmp_path / "reference.json"
    report = tmp_path / "report.json"
    manifests.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifests": [
                    {
                        "repository": "acme/app",
                        "path": "app.json",
                        "app_json": {
                            "idRanges": [
                                {"from": 1, "to": 1},
                                {"from": 50000, "to": 50000},
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reference.write_text(
        json.dumps({"Team": {"ranges": [{"from": 1, "to": 50000}]}}),
        encoding="utf-8",
    )

    assert main(
        [
            "object-ranges",
            "report",
            "--app-json",
            str(manifests),
            "--reference",
            str(reference),
            "--output",
            str(report),
            "--hide-range-type",
            "customization",
            "--ignore-range-type",
            "base",
        ]
    ) == 0

    document = json.loads(report.read_text(encoding="utf-8"))
    assert document["filters"] == {
        "hidden_range_types": ["customization"],
        "ignored_range_types": ["base"],
        "conflict_range_types": [
            "app",
            "base",
            "localization",
            "rsp",
            "unclassified",
        ],
    }
    assert document["groups"][0]["allocations"] == []
    assert document["summary"]["reference_ranges"] == 1
    assert document["summary"]["reserved_numbers"] == 1
    assert document["summary"]["unreserved_numbers"] == 0
