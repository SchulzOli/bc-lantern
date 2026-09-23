from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol, Sequence

from bc_lantern import __version__
from bc_lantern.app_json import InvalidAppJsonError, GitHubClient, retrieve_app_json
from bc_lantern.cache import CacheStore, JsonCacheStore
from bc_lantern.cli_docs import sync_cli_reference
from bc_lantern.github import GhClient, TruncatedTreeError
from bc_lantern.object_ranges import (
    DEFAULT_CONFLICT_RANGE_TYPES,
    RANGE_TYPES,
    ObjectRangeDataError,
    build_object_range_report,
    write_object_range_report,
)


class CliGitHubClient(GitHubClient, Protocol):
    def authenticated_user(self) -> str: ...


def default_cache_directory() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "bc-lantern" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "bc-lantern"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "bc-lantern"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bcl", description="BC Lantern tools for Business Central and AL"
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"bcl {__version__}",
        help="Print the installed BC Lantern version and exit",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    app_json = commands.add_parser(
        "app-json", help="Work with Business Central app.json manifests"
    )
    app_json_commands = app_json.add_subparsers(
        dest="app_json_command", required=True
    )
    retrieve = app_json_commands.add_parser(
        "retrieve",
        help="Download app.json files from GitHub repositories containing AL apps",
    )
    retrieve.add_argument(
        "--owner",
        help="GitHub user or organization (default: authenticated gh user)",
    )
    retrieve.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived repositories (excluded by default)",
    )
    retrieve.add_argument(
        "--output",
        type=Path,
        default=Path("app-json.json"),
        help="Aggregate JSON output file (default: ./app-json.json)",
    )
    retrieve.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_directory(),
        help="Cache directory (default: platform user cache directory)",
    )
    retrieve.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore fingerprints and rescan every selected repository",
    )
    retrieve.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable reading and writing the local cache",
    )

    object_ranges = commands.add_parser(
        "object-ranges",
        help="Analyze app.json objectRanges against allocated number ranges",
    )
    object_range_commands = object_ranges.add_subparsers(
        dest="object_ranges_command", required=True
    )
    report = object_range_commands.add_parser(
        "report",
        help="Report free ranges, current use, conflicts, and out-of-policy ranges",
    )
    report.add_argument(
        "--app-json",
        type=Path,
        default=Path("app-json.json"),
        help="Aggregate app.json input (default: ./app-json.json)",
    )
    report.add_argument(
        "--reference",
        type=Path,
        required=True,
        help="Reference object_ranges.json containing named allocated ranges",
    )
    report.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Report output file for --output-format "
            "(default: ./object-range-report.json when no format-specific "
            "output option is used)"
        ),
    )
    report.add_argument(
        "--output-format",
        choices=("json", "markdown"),
        default="json",
        help="Format of the --output file: json or markdown (default: json)",
    )
    report.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Additional JSON report file written from the same analysis",
    )
    report.add_argument(
        "--markdown-output",
        type=Path,
        default=None,
        help="Additional Markdown report file written from the same analysis",
    )
    report.add_argument(
        "--hide-range-type",
        action="append",
        choices=RANGE_TYPES,
        default=[],
        metavar="TYPE",
        help=(
            "Hide a type's details but still count it as occupied; repeatable. "
            f"Types: {', '.join(RANGE_TYPES)}"
        ),
    )
    report.add_argument(
        "--ignore-range-type",
        action="append",
        choices=RANGE_TYPES,
        default=[],
        metavar="TYPE",
        help=(
            "Ignore a type in occupancy, conflicts, and free-range calculations; "
            f"repeatable. Types: {', '.join(RANGE_TYPES)}"
        ),
    )
    report.add_argument(
        "--conflict-range-type",
        action="append",
        choices=RANGE_TYPES,
        default=None,
        metavar="TYPE",
        help=(
            "Include a type in conflict detection; repeatable. Supplying any "
            "values replaces the default set. When omitted, all types except "
            "customization are conflicting. "
            f"Default: {', '.join(DEFAULT_CONFLICT_RANGE_TYPES)}"
        ),
    )

    docs = commands.add_parser(
        "docs", help="Generate synchronized command-line reference documentation"
    )
    docs_commands = docs.add_subparsers(dest="docs_command", required=True)
    sync = docs_commands.add_parser(
        "sync",
        help="Write or verify docs/cli-reference.md from the live CLI parser",
    )
    sync.add_argument(
        "--output",
        type=Path,
        default=Path("docs/cli-reference.md"),
        help="Generated Markdown file (default: ./docs/cli-reference.md)",
    )
    sync.add_argument(
        "--check",
        action="store_true",
        help="Check that the output is current without changing it",
    )
    return parser


DEFAULT_REPORT_OUTPUT = Path("object-range-report.json")


def _report_targets(args: argparse.Namespace) -> list[tuple[Path, str]]:
    """Resolve every report file to write, keeping one analysis for all formats."""
    targets: list[tuple[Path, str]] = []
    if args.output is not None:
        targets.append((args.output, args.output_format))
    if args.json_output is not None:
        targets.append((args.json_output, "json"))
    if args.markdown_output is not None:
        targets.append((args.markdown_output, "markdown"))
    if not targets:
        targets.append((DEFAULT_REPORT_OUTPUT, args.output_format))
    return targets


def main(
    argv: Sequence[str] | None = None,
    *,
    client: CliGitHubClient | None = None,
    cache: CacheStore | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    github = client or GhClient()

    try:
        if args.command == "app-json" and args.app_json_command == "retrieve":
            owner = args.owner or github.authenticated_user()
            active_cache = None
            if not args.no_cache:
                active_cache = cache or JsonCacheStore(args.cache_dir)
            result = retrieve_app_json(
                github,
                owner,
                args.output,
                include_archived=args.include_archived,
                cache=active_cache,
                refresh=args.refresh,
            )
            print(f"Repositories scanned: {result.repositories_scanned}")
            print(f"Repositories updated: {result.repositories_updated}")
            print(f"Repositories from cache: {result.repositories_cached}")
            print(f"AL repositories: {result.al_repositories}")
            print(f"app.json files downloaded: {result.manifests_downloaded}")
            print(f"app.json files unchanged: {result.manifests_unchanged}")
            print(f"app.json files removed: {result.manifests_removed}")
            print(f"Output file: {args.output.resolve()}")
            if active_cache:
                cache_root = getattr(active_cache, "root", args.cache_dir)
                print(f"Cache: {Path(cache_root).resolve()}")
            return 0

        if args.command == "object-ranges" and args.object_ranges_command == "report":
            targets = _report_targets(args)
            report, result = build_object_range_report(
                args.app_json,
                args.reference,
                hidden_range_types=set(args.hide_range_type),
                ignored_range_types=set(args.ignore_range_type),
                conflict_range_types=(
                    None
                    if args.conflict_range_type is None
                    else set(args.conflict_range_type)
                ),
            )
            for path, output_format in targets:
                write_object_range_report(
                    report, path, output_format=output_format
                )
            print(f"Reference ranges: {result.reference_ranges}")
            print(f"Typed reference segments: {result.typed_reference_segments}")
            print(f"Declared ranges: {result.declared_ranges}")
            print(f"Typed declared segments: {result.typed_declared_segments}")
            print(f"Unreserved ranges: {result.unreserved_ranges}")
            print(f"Reserved object numbers: {result.reserved_numbers}")
            print(f"Unreserved object numbers: {result.unreserved_numbers}")
            print(f"Conflicts: {result.conflicts}")
            print(f"Outside declarations: {result.outside_declarations}")
            print(f"Outside-reference segments: {result.outside_reference}")
            for path, output_format in targets:
                print(f"Output file ({output_format}): {path.resolve()}")
            return 0

        if args.command == "docs" and args.docs_command == "sync":
            current = sync_cli_reference(
                args.output,
                check=args.check,
                parser=build_parser(),
            )
            if args.check:
                if current:
                    print(f"CLI documentation is current: {args.output.resolve()}")
                    return 0
                print(
                    f"CLI documentation is out of date: {args.output.resolve()}",
                    file=sys.stderr,
                )
                return 1
            print(f"CLI documentation synchronized: {args.output.resolve()}")
            return 0
    except (InvalidAppJsonError, ObjectRangeDataError, TruncatedTreeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except FileNotFoundError as error:
        if args.command == "object-ranges":
            missing_path = error.filename or "unknown"
            print(f"Input file not found: {missing_path}", file=sys.stderr)
            return 1
        print(
            "Error: GitHub CLI 'gh' was not found. Install it and run 'gh auth login'.",
            file=sys.stderr,
        )
        return 2
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if error.stderr else str(error)
        print(f"GitHub CLI failed: {detail}", file=sys.stderr)
        return error.returncode or 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
