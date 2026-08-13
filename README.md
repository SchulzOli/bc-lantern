# BCCLI

A small command-line helper for Microsoft Dynamics 365 Business Central and AL.

## First feature: retrieve `app.json` files from GitHub

`bccli app-json retrieve` uses GitHub's own `gh` CLI to:

1. list repositories for a GitHub user or organization;
2. inspect each default branch for AL (`.al`) source files;
3. retrieve every `app.json` from repositories that actually contain AL code;
4. write one aggregate `app-json.json` artifact containing repository metadata and parsed manifest content;
5. cache repository fingerprints, Git blob SHAs, and parsed manifests so later runs only retrieve changes.

Archived repositories are excluded by default and can be enabled with a switch.
Private repositories are included when the authenticated `gh` account can access them.

## Incremental cache

Caching is enabled by default. BCCLI stores reusable, feature-namespaced JSON state under the operating system's user cache directory:

```text
Windows: %LOCALAPPDATA%\bccli\cache
macOS:   ~/Library/Caches/bccli
Linux:   ${XDG_CACHE_HOME:-~/.cache}/bccli
```

The cache layer is independent of `app.json`, so later GitHub or Business Central features can use the same `JsonCacheStore` and generic incremental planner with separate namespaces and schemas.

Every run still asks `gh repo list` for lightweight repository metadata. It then:

- skips tree inspection for repositories whose default branch, pushed timestamp, and archived state are unchanged;
- compares Git blob SHAs when a repository changed;
- downloads only new or modified manifests into the cache;
- drops manifests deleted upstream from the cache and aggregate artifact;
- rebuilds a missing aggregate output entirely from cache without another content download.

Force a full rescan:

```text
bccli app-json retrieve --refresh
```

Use a custom cache location:

```text
bccli app-json retrieve --cache-dir C:\path\to\cache
```

Disable cache reads and writes:

```text
bccli app-json retrieve --no-cache
```

## Requirements

- Python 3.10+
- [GitHub CLI](https://cli.github.com/) installed and authenticated:

```text
gh auth login
```

## Install for development

```text
python -m pip install -e ".[dev]"
```

Or, when `uv` is available:

```text
uv tool install --editable .
```

## Usage

Retrieve from the currently authenticated GitHub user's repositories:

```text
bccli app-json retrieve
```

Include archived repositories:

```text
bccli app-json retrieve --include-archived
```

Retrieve from a user or organization and select the output file:

```text
bccli app-json retrieve --owner my-organization --output ./manifests.json
```

The output is one machine-readable JSON document. It is intentionally shaped as an internal data artifact for later BCCLI commands:

```json
{
  "schema_version": 1,
  "owner": "my-organization",
  "include_archived": false,
  "manifests": [
    {
      "repository": "my-organization/my-extension",
      "default_branch": "main",
      "archived": false,
      "path": "app/app.json",
      "fingerprint": "<Git blob SHA>",
      "app_json": {
        "id": "...",
        "name": "My Extension",
        "publisher": "...",
        "version": "1.0.0.0"
      }
    }
  ]
}
```

No repository folder tree or individual manifest files are created.

## PowerShell example

[`example.ps1`](example.ps1) rebuilds and validates JSON and Markdown reports.
Pass the GitHub owner and your local allocation file explicitly:

```powershell
.\example.ps1 -Owner my-organization -Reference C:\path\to\object_ranges.json
```

Generated aggregates and reports are ignored by Git because they can contain
repository metadata and are reproducible from their source data.

## Object-range analysis

After retrieving manifests, compare every declared inclusive Business Central `idRanges` interval (and legacy/alternate `objectRanges`) with a named allocation file such as `object_ranges.json`:

```text
bccli object-ranges report \
  --app-json ./app-json.json \
  --reference "C:\path\to\object_ranges.json" \
  --output ./object-range-report.json
```

`--app-json` defaults to `./app-json.json`, `--output` defaults to `./object-range-report.json`, and `--output-format` defaults to `json`.

The report output object supports exactly two formats:

- `json` — machine-readable schema-versioned data;
- `markdown` — human-readable schema/category metadata plus summary, allocation, reservation, restricted-table-use, unreserved-range, conflict, and outside-reference tables. Conflict and outside-reference source cells use line breaks for app/version, repository, manifest, declared range, and app ID instead of dense `key=value` text; multiple conflict sources are additionally numbered.

```text
bccli object-ranges report \
  --reference object_ranges.json \
  --output object-range-report.md \
  --output-format markdown
```

`idRanges` takes precedence when a manifest contains both fields, preventing the same reservation from being counted twice; `objectRanges` is used only as a legacy fallback.

The report is a manifest-reservation comparison, not an implemented-object scan. Schema version 4 therefore uses `reserved_numbers`, `unreserved_numbers`, `unreserved_ranges`, `reserved_count`, `unreserved_count`, and `reservations`; it does not label reserved IDs as actual object usage. Schema 4 also records the independently selected `conflict_range_types`.

The report contains:

- each named reference group and its allocation ranges;
- every matching reservation, attributed to aggregate manifest record index, repository, manifest path, app ID, name, publisher, version, source field (`idRanges` or `objectRanges`), and original declared bounds;
- unreserved inclusive subranges and their sizes;
- total reserved/unreserved object-number counts for each allocation;
- overlaps where multiple apps declare the same object numbers;
- declared object ranges or partial ranges that fall outside all reference allocations;
- `restricted_table_use` intervals from each reference group, category-split and subject to the same hide/ignore presentation semantics, for later object-type-aware checks.

The report classifies every declaration using Microsoft's documented Business Central range types:

| Type | Inclusive IDs |
|---|---:|
| `base` | 0–49,999 |
| `customization` | 50,000–99,999 |
| `localization` | 100,000–999,999 |
| `rsp` | 1,000,000–69,999,999 |
| `app` | 70,000,000–74,999,999 |
| `unclassified` | 75,000,000 and above (or other future gaps) |

A declaration or reference allocation that crosses a boundary is split into correctly typed comparison segments. `summary.reference_ranges` counts original applicable reference allocations and `summary.typed_reference_segments` counts their category-split comparison pieces. `summary.declared_ranges` counts original applicable manifest declarations, while `summary.typed_declared_segments` counts the category-split declaration segments used for filtering and comparison. Likewise, `summary.outside_declarations` counts original declarations with at least one outside segment and `summary.outside_reference` counts calculated typed outside segments; hidden segments remain in these summary totals even when their detail records are omitted.

All endpoints are non-negative inclusive integers, so interval size is `to - from + 1`. Reserved intersections are merged only for subtraction and totals; original declarations stay separate for attribution and conflict detection. Overlapping reference allocations are rejected because they would otherwise double-count the comparison domain; directly adjacent allocations remain valid.

By default, conflict detection includes `base`, `localization`, `rsp`, `app`, and `unclassified`. The `customization` range (`50,000..99,999`) is deliberately non-conflicting because it is commonly shared by tests and prototypes. This affects only conflict findings and their count; reservation and unreserved-range calculations still include `customization` normally.

Select the conflict-enabled types explicitly with repeatable `--conflict-range-type` options. Supplying the option replaces the default set. For example, to make only `customization` conflict-enabled:

```text
bccli object-ranges report --reference object_ranges.json \
  --conflict-range-type customization
```

To use every range type for conflict detection, repeat the option for `base`, `customization`, `localization`, `rsp`, `app`, and `unclassified`.

Hide one or more types from detailed report sections while still counting their numbers, conflicts, and outside-reference findings in summary calculations:

```text
bccli object-ranges report --reference object_ranges.json \
  --hide-range-type base \
  --hide-range-type localization
```

Ignore one or more types entirely. Ignored declarations and matching reference-allocation segments are removed before reservation, conflict, outside-reference, and unreserved-range calculations; ignored number spaces are not reported as unreserved. For example, this prevents `50,000..99,999` from appearing in the outside-reference summary and detail table:

```text
bccli object-ranges report --reference object_ranges.json \
  --ignore-range-type customization
```

Both options are repeatable and can be combined. Valid values are `base`, `customization`, `localization`, `rsp`, `app`, and `unclassified`. The applied filters are stored in the generated report.

## Synchronized CLI reference

The complete command and option reference is generated from the same `argparse` definitions used at runtime:

```text
bccli docs sync
```

This writes [`docs/cli-reference.md`](docs/cli-reference.md). Do not edit that generated file manually. After adding, removing, or changing a CLI command or option, regenerate it with `bccli docs sync`.

CI or local validation can detect documentation drift without modifying files:

```text
bccli docs sync --check
```

The check returns exit code `0` when the committed reference is current and `1` when it is missing or stale. Use `--output PATH` on either form to target another reference file.

The current analysis operates on ranges declared by `app.json`. It identifies where numbers are reserved/declared, not which individual AL object IDs actually exist inside those ranges.

Run `bccli app-json retrieve --help`, `bccli object-ranges report --help`, or consult the [generated CLI reference](docs/cli-reference.md) for all options.

## Tests

```text
python -m pytest
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development and pull-request
workflow. Report security issues as described in [SECURITY.md](SECURITY.md).

## License

Licensed under the [MIT License](LICENSE).
