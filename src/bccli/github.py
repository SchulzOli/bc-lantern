from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

Runner = Callable[..., subprocess.CompletedProcess[str]]


class TruncatedTreeError(RuntimeError):
    """Raised when GitHub cannot return a repository's complete recursive tree."""


@dataclass(frozen=True)
class Repository:
    name_with_owner: str
    is_archived: bool
    default_branch: str
    pushed_at: str = ""


@dataclass(frozen=True)
class RepositoryFile:
    path: str
    fingerprint: str


class GhClient:
    def __init__(self, runner: Runner = subprocess.run) -> None:
        self._runner = runner

    def authenticated_user(self) -> str:
        result = self._runner(
            ["gh", "api", "user", "--jq", ".login"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def list_repositories(
        self, owner: str, *, include_archived: bool = False
    ) -> list[Repository]:
        result = self._runner(
            [
                "gh",
                "repo",
                "list",
                owner,
                "--limit",
                "1000",
                "--json",
                "nameWithOwner,isArchived,defaultBranchRef,pushedAt",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload: list[dict[str, Any]] = json.loads(result.stdout)
        repositories = [
            Repository(
                name_with_owner=item["nameWithOwner"],
                is_archived=item["isArchived"],
                default_branch=item["defaultBranchRef"]["name"],
                pushed_at=item.get("pushedAt") or "",
            )
            for item in payload
            if item.get("defaultBranchRef")
        ]
        if include_archived:
            return repositories
        return [repository for repository in repositories if not repository.is_archived]

    def find_app_json_files(self, repository: Repository) -> list[RepositoryFile]:
        encoded_repository = "/".join(
            quote(part, safe="") for part in repository.name_with_owner.split("/")
        )
        encoded_branch = quote(repository.default_branch, safe="")
        result = self._runner(
            [
                "gh",
                "api",
                (
                    f"repos/{encoded_repository}/git/trees/"
                    f"{encoded_branch}?recursive=1"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload: dict[str, Any] = json.loads(result.stdout)
        if payload.get("truncated"):
            raise TruncatedTreeError(
                f"GitHub returned a truncated tree for {repository.name_with_owner}"
            )
        tree_items = payload.get("tree", [])
        has_al_code = any(
            item.get("type") == "blob"
            and item.get("path", "").lower().endswith(".al")
            for item in tree_items
        )
        if not has_al_code:
            return []
        return sorted(
            (
                RepositoryFile(
                    path=item["path"], fingerprint=str(item.get("sha", ""))
                )
                for item in tree_items
                if item.get("type") == "blob"
                and item.get("path", "").rsplit("/", 1)[-1].lower()
                == "app.json"
            ),
            key=lambda item: item.path,
        )

    def get_file(self, repository: Repository, path: str) -> str:
        encoded_repository = "/".join(
            quote(part, safe="") for part in repository.name_with_owner.split("/")
        )
        encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
        encoded_branch = quote(repository.default_branch, safe="")
        result = self._runner(
            [
                "gh",
                "api",
                "-H",
                "Accept: application/vnd.github.raw+json",
                (
                    f"repos/{encoded_repository}/contents/{encoded_path}"
                    f"?ref={encoded_branch}"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
