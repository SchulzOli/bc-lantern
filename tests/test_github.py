from __future__ import annotations

import json
import subprocess

import pytest

from bccli.github import GhClient, Repository, RepositoryFile, TruncatedTreeError


def completed(args: list[str], stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


def test_list_repositories_excludes_archived_by_default() -> None:
    payload = [
        {
            "nameWithOwner": "acme/current-app",
            "isArchived": False,
            "defaultBranchRef": {"name": "main"},
        },
        {
            "nameWithOwner": "acme/old-app",
            "isArchived": True,
            "defaultBranchRef": {"name": "main"},
        },
    ]

    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return completed(args, json.dumps(payload))

    repositories = GhClient(runner=runner).list_repositories("acme")

    assert [repo.name_with_owner for repo in repositories] == ["acme/current-app"]


def test_list_repositories_can_include_archived_repositories() -> None:
    payload = [
        {
            "nameWithOwner": "acme/current-app",
            "isArchived": False,
            "defaultBranchRef": {"name": "main"},
        },
        {
            "nameWithOwner": "acme/old-app",
            "isArchived": True,
            "defaultBranchRef": {"name": "legacy"},
        },
    ]

    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return completed(args, json.dumps(payload))

    repositories = GhClient(runner=runner).list_repositories(
        "acme", include_archived=True
    )

    assert [repo.name_with_owner for repo in repositories] == [
        "acme/current-app",
        "acme/old-app",
    ]
    assert repositories[1].default_branch == "legacy"


def test_find_app_json_files_reads_the_default_branch_tree() -> None:
    repository = Repository("acme/al app", False, "release/v1")
    tree = {
        "tree": [
            {"path": "app.json", "type": "blob", "sha": "root-sha"},
            {"path": "test/app.json", "type": "blob", "sha": "test-sha"},
            {"path": "src/Codeunit.al", "type": "blob"},
            {"path": "samples/app.json", "type": "tree"},
        ],
        "truncated": False,
    }
    calls: list[list[str]] = []

    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, json.dumps(tree))

    paths = GhClient(runner=runner).find_app_json_files(repository)

    assert paths == [
        RepositoryFile("app.json", "root-sha"),
        RepositoryFile("test/app.json", "test-sha"),
    ]
    assert calls == [
        [
            "gh",
            "api",
            "repos/acme/al%20app/git/trees/release%2Fv1?recursive=1",
        ]
    ]


def test_get_file_uses_the_raw_github_media_type() -> None:
    repository = Repository("acme/al app", False, "release/v1")
    calls: list[list[str]] = []

    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, '{"name": "AL app"}')

    content = GhClient(runner=runner).get_file(repository, "test app/app.json")

    assert content == '{"name": "AL app"}'
    assert calls == [
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github.raw+json",
            "repos/acme/al%20app/contents/test%20app/app.json?ref=release%2Fv1",
        ]
    ]


def test_find_app_json_files_rejects_a_truncated_git_tree() -> None:
    repository = Repository("acme/huge", False, "main")

    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return completed(args, json.dumps({"tree": [], "truncated": True}))

    with pytest.raises(TruncatedTreeError, match="acme/huge"):
        GhClient(runner=runner).find_app_json_files(repository)


def test_find_app_json_files_ignores_repository_without_al_code() -> None:
    repository = Repository("acme/web-app", False, "main")
    tree = {
        "tree": [
            {"path": "app.json", "type": "blob"},
            {"path": "src/index.js", "type": "blob"},
        ],
        "truncated": False,
    }

    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return completed(args, json.dumps(tree))

    assert GhClient(runner=runner).find_app_json_files(repository) == []
