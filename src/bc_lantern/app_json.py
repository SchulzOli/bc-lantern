from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from bc_lantern.cache import CacheStore
from bc_lantern.github import Repository, RepositoryFile
from bc_lantern.incremental import plan_incremental
from bc_lantern.json_io import write_json_atomic

CACHE_NAMESPACE = "github/app-json/v3"
CACHE_SCHEMA_VERSION = 2
ARTIFACT_SCHEMA_VERSION = 1


class GitHubClient(Protocol):
    def list_repositories(
        self, owner: str, *, include_archived: bool = False
    ) -> list[Repository]: ...

    def find_app_json_files(
        self, repository: Repository
    ) -> list[RepositoryFile]: ...

    def get_file(self, repository: Repository, path: str) -> str: ...


class InvalidAppJsonError(ValueError):
    """Raised when a retrieved app.json is not a JSON object."""


@dataclass(frozen=True)
class ManifestRecord:
    path: str
    fingerprint: str
    app_json: dict[str, Any]


@dataclass(frozen=True)
class RetrievalResult:
    repositories_scanned: int
    al_repositories: int
    manifests_downloaded: int
    repositories_updated: int = 0
    repositories_cached: int = 0
    manifests_unchanged: int = 0
    manifests_removed: int = 0


def retrieve_app_json(
    client: GitHubClient,
    owner: str,
    output_file: Path,
    *,
    include_archived: bool = False,
    cache: CacheStore | None = None,
    refresh: bool = False,
) -> RetrievalResult:
    repositories = client.list_repositories(
        owner, include_archived=include_archived
    )
    state = cache.get(CACHE_NAMESPACE, owner) if cache else None
    cached_repositories = _repository_entries(state)
    repositories_by_name = {
        repository.name_with_owner: repository for repository in repositories
    }
    current_fingerprints = {
        name: _repository_fingerprint(repository)
        for name, repository in repositories_by_name.items()
    }
    cached_fingerprints = {
        name: str(entry.get("fingerprint", ""))
        for name, entry in cached_repositories.items()
    }
    incremental_plan = plan_incremental(
        current_fingerprints, cached_fingerprints, force=refresh
    )
    unchanged_names = set(incremental_plan.unchanged)
    next_repositories: dict[str, dict[str, Any]] = {}

    al_repositories = 0
    manifests_downloaded = 0
    repositories_updated = 0
    repositories_cached = 0
    manifests_unchanged = 0
    manifests_removed = 0

    for repository in repositories:
        old_entry = cached_repositories.get(repository.name_with_owner, {})
        old_records = _manifest_records(old_entry)
        old_by_path = {record.path: record for record in old_records}

        if repository.name_with_owner in unchanged_names:
            records = old_records
            repositories_cached += 1
            manifests_unchanged += len(records)
        else:
            remote_files = client.find_app_json_files(repository)
            remote_by_path = {item.path: item for item in remote_files}
            records = []
            repositories_updated += 1
            manifests_removed += len(set(old_by_path) - set(remote_by_path))

            for remote_file in remote_files:
                old_record = old_by_path.get(remote_file.path)
                if (
                    old_record is not None
                    and old_record.fingerprint == remote_file.fingerprint
                ):
                    record = old_record
                    manifests_unchanged += 1
                else:
                    record = ManifestRecord(
                        path=remote_file.path,
                        fingerprint=remote_file.fingerprint,
                        app_json=_parse_app_json(
                            client.get_file(repository, remote_file.path),
                            repository.name_with_owner,
                            remote_file.path,
                        ),
                    )
                    manifests_downloaded += 1
                records.append(record)

        records.sort(key=lambda item: item.path)
        if records:
            al_repositories += 1
        next_repositories[repository.name_with_owner] = _repository_entry(
            repository, records
        )

    for removed_repository in incremental_plan.removed:
        removed_entry = cached_repositories[removed_repository]
        if not include_archived and _entry_is_archived(removed_entry):
            next_repositories[removed_repository] = removed_entry
        else:
            manifests_removed += len(_manifest_records(removed_entry))

    if cache:
        cache.put(
            CACHE_NAMESPACE,
            owner,
            {
                "schema_version": CACHE_SCHEMA_VERSION,
                "repositories": next_repositories,
            },
        )

    artifact = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "owner": owner,
        "include_archived": include_archived,
        "manifests": _artifact_manifests(repositories, next_repositories),
    }
    write_json_atomic(output_file, artifact)

    return RetrievalResult(
        repositories_scanned=len(repositories),
        al_repositories=al_repositories,
        manifests_downloaded=manifests_downloaded,
        repositories_updated=repositories_updated,
        repositories_cached=repositories_cached,
        manifests_unchanged=manifests_unchanged,
        manifests_removed=manifests_removed,
    )


def _parse_app_json(
    content: str, repository_name: str, manifest_path: str
) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        raise InvalidAppJsonError(
            f"Invalid JSON in {repository_name}:{manifest_path}: {error.msg}"
        ) from error
    if not isinstance(value, dict):
        raise InvalidAppJsonError(
            f"Expected a JSON object in {repository_name}:{manifest_path}"
        )
    return value


def _repository_entries(state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not state or state.get("schema_version") != CACHE_SCHEMA_VERSION:
        return {}
    repositories = state.get("repositories")
    return repositories if isinstance(repositories, dict) else {}


def _entry_is_archived(entry: dict[str, Any]) -> bool:
    return entry.get("archived") is True


def _manifest_records(entry: dict[str, Any]) -> list[ManifestRecord]:
    manifests = entry.get("manifests", [])
    if not isinstance(manifests, list):
        return []
    records: list[ManifestRecord] = []
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        path = manifest.get("path")
        fingerprint = manifest.get("fingerprint")
        app_json = manifest.get("app_json")
        if (
            isinstance(path, str)
            and isinstance(fingerprint, str)
            and isinstance(app_json, dict)
        ):
            records.append(ManifestRecord(path, fingerprint, app_json))
    return sorted(records, key=lambda item: item.path)


def _repository_entry(
    repository: Repository, records: list[ManifestRecord]
) -> dict[str, Any]:
    return {
        "fingerprint": _repository_fingerprint(repository),
        "default_branch": repository.default_branch,
        "archived": repository.is_archived,
        "manifests": [
            {
                "path": record.path,
                "fingerprint": record.fingerprint,
                "app_json": record.app_json,
            }
            for record in records
        ],
    }


def _repository_fingerprint(repository: Repository) -> str:
    return "|".join(
        (
            repository.default_branch,
            repository.pushed_at,
            "archived" if repository.is_archived else "active",
        )
    )


def _artifact_manifests(
    repositories: list[Repository],
    repository_entries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for repository in sorted(repositories, key=lambda item: item.name_with_owner):
        entry = repository_entries[repository.name_with_owner]
        for record in _manifest_records(entry):
            manifests.append(
                {
                    "repository": repository.name_with_owner,
                    "default_branch": repository.default_branch,
                    "archived": repository.is_archived,
                    "path": record.path,
                    "fingerprint": record.fingerprint,
                    "app_json": record.app_json,
                }
            )
    return manifests
