from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bccli.app_json import retrieve_app_json
from bccli.cache import JsonCacheStore
from bccli.github import Repository, RepositoryFile


@dataclass
class FakeGhClient:
    repositories: list[Repository]
    files: dict[str, dict[str, str]]
    tree_calls: list[str] | None = None
    file_calls: list[tuple[str, str]] | None = None

    def list_repositories(
        self, owner: str, *, include_archived: bool = False
    ) -> list[Repository]:
        repositories = [
            repository
            for repository in self.repositories
            if repository.name_with_owner.startswith(f"{owner}/")
        ]
        if include_archived:
            return repositories
        return [repository for repository in repositories if not repository.is_archived]

    def find_app_json_files(self, repository: Repository) -> list[RepositoryFile]:
        if self.tree_calls is not None:
            self.tree_calls.append(repository.name_with_owner)
        return [
            RepositoryFile(path, content)
            for path, content in sorted(
                self.files.get(repository.name_with_owner, {}).items()
            )
        ]

    def get_file(self, repository: Repository, path: str) -> str:
        if self.file_calls is not None:
            self.file_calls.append((repository.name_with_owner, path))
        return self.files[repository.name_with_owner][path]


def test_retrieve_app_json_writes_one_aggregate_json_file(tmp_path: Path) -> None:
    client = FakeGhClient(
        repositories=[
            Repository("acme/one", False, "main"),
            Repository("acme/two", False, "develop"),
            Repository("acme/no-al", False, "main"),
            Repository("acme/archived", True, "main"),
        ],
        files={
            "acme/one": {"app.json": '{"name": "One"}'},
            "acme/two": {
                "app/app.json": '{"name": "Two"}',
                "test/app.json": '{"name": "Two Test"}',
            },
            "acme/archived": {"app.json": '{"name": "Old"}'},
        },
    )

    output_file = tmp_path / "app-json.json"
    result = retrieve_app_json(client, "acme", output_file)

    assert result.repositories_scanned == 3
    assert result.al_repositories == 2
    assert result.manifests_downloaded == 3
    artifact = json.loads(output_file.read_text(encoding="utf-8"))
    assert artifact == {
        "schema_version": 1,
        "owner": "acme",
        "include_archived": False,
        "manifests": [
            {
                "repository": "acme/one",
                "default_branch": "main",
                "archived": False,
                "path": "app.json",
                "fingerprint": '{"name": "One"}',
                "app_json": {"name": "One"},
            },
            {
                "repository": "acme/two",
                "default_branch": "develop",
                "archived": False,
                "path": "app/app.json",
                "fingerprint": '{"name": "Two"}',
                "app_json": {"name": "Two"},
            },
            {
                "repository": "acme/two",
                "default_branch": "develop",
                "archived": False,
                "path": "test/app.json",
                "fingerprint": '{"name": "Two Test"}',
                "app_json": {"name": "Two Test"},
            },
        ],
    }
    assert list(tmp_path.iterdir()) == [output_file]


def test_retrieve_app_json_can_include_archived_repositories(tmp_path: Path) -> None:
    client = FakeGhClient(
        repositories=[Repository("acme/archived", True, "main")],
        files={"acme/archived": {"app.json": '{"name": "Old"}'}},
    )

    output_file = tmp_path / "app-json.json"
    result = retrieve_app_json(
        client, "acme", output_file, include_archived=True
    )

    assert result.al_repositories == 1
    artifact = json.loads(output_file.read_text(encoding="utf-8"))
    assert artifact["include_archived"] is True
    assert artifact["manifests"][0]["repository"] == "acme/archived"
    assert artifact["manifests"][0]["app_json"] == {"name": "Old"}


def test_retrieve_app_json_uses_cache_for_unchanged_repositories(
    tmp_path: Path,
) -> None:
    output = tmp_path / "app-json.json"
    cache = JsonCacheStore(tmp_path / "cache")
    tree_calls: list[str] = []
    file_calls: list[tuple[str, str]] = []
    client = FakeGhClient(
        repositories=[
            Repository("acme/one", False, "main", "2026-08-12T10:00:00Z")
        ],
        files={"acme/one": {"app.json": '{"name": "One"}'}},
        tree_calls=tree_calls,
        file_calls=file_calls,
    )

    first = retrieve_app_json(client, "acme", output, cache=cache)
    second = retrieve_app_json(client, "acme", output, cache=cache)

    assert first.repositories_updated == 1
    assert second.repositories_updated == 0
    assert second.repositories_cached == 1
    assert second.manifests_downloaded == 0
    assert second.manifests_unchanged == 1
    assert tree_calls == ["acme/one"]
    assert file_calls == [("acme/one", "app.json")]


def test_retrieve_app_json_updates_only_changed_manifests(tmp_path: Path) -> None:
    output = tmp_path / "app-json.json"
    cache = JsonCacheStore(tmp_path / "cache")
    tree_calls: list[str] = []
    file_calls: list[tuple[str, str]] = []
    client = FakeGhClient(
        repositories=[
            Repository("acme/one", False, "main", "2026-08-12T10:00:00Z")
        ],
        files={
            "acme/one": {
                "app.json": '{"name": "One"}',
                "test/app.json": '{"name": "Test"}',
            }
        },
        tree_calls=tree_calls,
        file_calls=file_calls,
    )
    retrieve_app_json(client, "acme", output, cache=cache)
    tree_calls.clear()
    file_calls.clear()
    client.repositories = [
        Repository("acme/one", False, "main", "2026-08-12T11:00:00Z")
    ]
    client.files["acme/one"]["test/app.json"] = '{"name": "Changed Test"}'

    result = retrieve_app_json(client, "acme", output, cache=cache)

    assert result.repositories_updated == 1
    assert result.manifests_downloaded == 1
    assert result.manifests_unchanged == 1
    assert tree_calls == ["acme/one"]
    assert file_calls == [("acme/one", "test/app.json")]
    artifact = json.loads(output.read_text(encoding="utf-8"))
    manifests = {
        (item["repository"], item["path"]): item["app_json"]
        for item in artifact["manifests"]
    }
    assert manifests[("acme/one", "app.json")] == {"name": "One"}
    assert manifests[("acme/one", "test/app.json")] == {
        "name": "Changed Test"
    }


def test_retrieve_app_json_removes_deleted_manifests_and_repositories(
    tmp_path: Path,
) -> None:
    output = tmp_path / "app-json.json"
    cache = JsonCacheStore(tmp_path / "cache")
    client = FakeGhClient(
        repositories=[
            Repository("acme/one", False, "main", "old"),
            Repository("acme/gone", False, "main", "old"),
        ],
        files={
            "acme/one": {
                "app.json": '{"name": "One"}',
                "test/app.json": '{"name": "Test"}',
            },
            "acme/gone": {"app.json": '{"name": "Gone"}'},
        },
    )
    retrieve_app_json(client, "acme", output, cache=cache)
    client.repositories = [Repository("acme/one", False, "main", "new")]
    del client.files["acme/one"]["test/app.json"]

    result = retrieve_app_json(client, "acme", output, cache=cache)

    assert result.manifests_removed == 2
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert [
        (item["repository"], item["path"])
        for item in artifact["manifests"]
    ] == [("acme/one", "app.json")]


def test_retrieve_app_json_rebuilds_missing_output_from_cache(tmp_path: Path) -> None:
    output = tmp_path / "app-json.json"
    cache = JsonCacheStore(tmp_path / "cache")
    file_calls: list[tuple[str, str]] = []
    client = FakeGhClient(
        repositories=[Repository("acme/one", False, "main", "same")],
        files={"acme/one": {"app.json": '{"name": "One"}'}},
        file_calls=file_calls,
    )
    retrieve_app_json(client, "acme", output, cache=cache)
    output.unlink()
    file_calls.clear()

    result = retrieve_app_json(client, "acme", output, cache=cache)

    assert result.repositories_cached == 1
    assert result.manifests_downloaded == 0
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["manifests"][0][
        "app_json"
    ] == {"name": "One"}
    assert file_calls == []


def test_archived_filter_shares_cache_without_deleting_archived_state(
    tmp_path: Path,
) -> None:
    output = tmp_path / "app-json.json"
    cache = JsonCacheStore(tmp_path / "cache")
    tree_calls: list[str] = []
    client = FakeGhClient(
        repositories=[
            Repository("acme/current", False, "main", "same"),
            Repository("acme/archived", True, "main", "same"),
        ],
        files={
            "acme/current": {"app.json": '{"name": "Current"}'},
            "acme/archived": {"app.json": '{"name": "Archived"}'},
        },
        tree_calls=tree_calls,
    )

    retrieve_app_json(
        client, "acme", output, include_archived=True, cache=cache
    )
    tree_calls.clear()
    without_archived = retrieve_app_json(client, "acme", output, cache=cache)
    without_archived_artifact = json.loads(output.read_text(encoding="utf-8"))
    with_archived_again = retrieve_app_json(
        client, "acme", output, include_archived=True, cache=cache
    )

    assert without_archived.repositories_cached == 1
    assert with_archived_again.repositories_cached == 2
    assert tree_calls == []
    assert [
        item["repository"] for item in without_archived_artifact["manifests"]
    ] == ["acme/current"]
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert [item["repository"] for item in artifact["manifests"]] == [
        "acme/archived",
        "acme/current",
    ]
