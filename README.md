# BC Lantern

BC Lantern is a Python command-line toolbox for Microsoft Dynamics 365 Business Central
and AL projects.

It can:

- collect `app.json` manifests from GitHub repositories that contain AL code;
- cache manifests and download only changed files;
- compare declared object ranges with a central allocation file;
- report reservations, free ranges, conflicts, and ranges outside the allocation;
- write object-range reports as JSON or Markdown.

## Requirements

- Python 3.10 or later
- [GitHub CLI](https://cli.github.com/) for `app-json retrieve`
- Git for installation directly from GitHub

Authenticate GitHub CLI before you collect manifests:

```text
gh auth login
```

The authenticated account controls access to private repositories.

## Install

### Install from PyPI

Use `pipx` to install BC Lantern in an isolated environment:

```text
pipx install bc-lantern
```

You can also use pip:

```text
python -m pip install bc-lantern
```

Upgrade an existing installation:

```text
pipx upgrade bc-lantern
```

### Install from GitHub

Install a specific release tag before or without a PyPI release:

```text
python -m pip install "bc-lantern @ git+https://github.com/SchulzOli/bc-lantern.git@v0.8.0"
```

Use a tag or full commit SHA in automated builds. Do not install from `main` in
a reproducible pipeline.

Verify the installation:

```text
bcl --version
```

`bcl --version` and `bcl -V` print the installed version and exit with status 0.

### Distribution channels

PyPI is the only supported package registry. BC Lantern is not published on npm.
GitHub workflows use the bundled composite action described in
[GitHub Actions](#github-actions), which installs a pinned PyPI release.

## Quick start

### 1. Collect `app.json` manifests

Collect manifests from the repositories of the authenticated GitHub account:

```text
bcl app-json retrieve
```

Collect manifests from a specified user or organization:

```text
bcl app-json retrieve \
  --owner my-organization \
  --output app-json.json
```

BC Lantern excludes archived repositories by default. Add `--include-archived` to
include them.

The command writes one aggregate JSON file. It does not create repository
folders or separate manifest files.

### 2. Create an allocation file

Create an `object_ranges.json` file with named allocations:

```json
{
  "My team": {
    "ranges": [
      { "from": 1000000, "to": 1000999 }
    ]
  }
}
```

Allocation ranges are inclusive. Reference allocations must not overlap.

### 3. Create an object-range report

Compare the collected manifests with the allocation file:

```text
bcl object-ranges report \
  --app-json app-json.json \
  --reference object_ranges.json \
  --output object-range-report.json
```

Create a Markdown report:

```text
bcl object-ranges report \
  --reference object_ranges.json \
  --output object-range-report.md \
  --output-format markdown
```

Create both formats from one analysis:

```text
bcl object-ranges report \
  --reference object_ranges.json \
  --json-output object-range-report.json \
  --markdown-output object-range-report.md
```

`--json-output` and `--markdown-output` read and analyze the inputs once. Use
`--output` with `--output-format` for a single file.

`--app-json` defaults to `app-json.json`. Without an output option, the report
is written to `object-range-report.json`.

The report compares declared reservations. It does not scan AL source files for
implemented object IDs.

## Range filters

BC Lantern classifies declared ranges with these Business Central categories:

| Type | Inclusive IDs |
|---|---:|
| `base` | 0-49,999 |
| `customization` | 50,000-99,999 |
| `localization` | 100,000-999,999 |
| `rsp` | 1,000,000-69,999,999 |
| `app` | 70,000,000-74,999,999 |
| `unclassified` | 75,000,000 and above |

Hide a category from report details but keep it in calculations:

```text
bcl object-ranges report \
  --reference object_ranges.json \
  --hide-range-type rsp
```

Remove a category from all calculations:

```text
bcl object-ranges report \
  --reference object_ranges.json \
  --ignore-range-type customization
```

Both options are repeatable. Use `--conflict-range-type` to replace the default
set of conflict-enabled categories. By default, all categories except
`customization` participate in conflict detection.

See the [CLI reference](docs/cli-reference.md) for every command and option.

## Cache

BC Lantern caches GitHub metadata and manifests by default:

```text
Windows: %LOCALAPPDATA%\bc-lantern\cache
macOS:   ~/Library/Caches/bc-lantern
Linux:   ${XDG_CACHE_HOME:-~/.cache}/bc-lantern
```

Force a complete scan:

```text
bcl app-json retrieve --refresh
```

Disable the cache:

```text
bcl app-json retrieve --no-cache
```

Set another cache directory:

```text
bcl app-json retrieve --cache-dir path/to/cache
```

## GitHub Actions

### Bundled composite action

This repository ships an official composite action. It installs a pinned PyPI
release, retrieves the manifests, and writes both report formats:

```yaml
name: Object range report

on:
  workflow_dispatch:
  schedule:
    - cron: "0 5 * * 1"

jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: SchulzOli/bc-lantern@v0.8.0
        id: lantern
        with:
          owner: my-organization
          reference: object_ranges.json
          json-output: object-range-report.json
          markdown-output: object-range-report.md
          github-token: ${{ secrets.BC_LANTERN_TOKEN }}

      - uses: actions/upload-artifact@v4
        with:
          name: object-range-report
          path: |
            ${{ steps.lantern.outputs.json-report }}
            ${{ steps.lantern.outputs.markdown-report }}
```

### Token scopes

`bcl app-json retrieve` uses GitHub CLI and reads `GH_TOKEN`. The automatic
`GITHUB_TOKEN` of a workflow is limited to the current repository. It usually
cannot enumerate and read all repositories of an organization, so a run can
succeed and still produce an incomplete report.

Use one of these tokens instead:

- a GitHub App installation token with `Contents: read` and `Metadata: read` for
  every intended repository;
- a personal access token with read access to every intended repository.

Store the token as a secret and pass it as `github-token`, or as `GH_TOKEN` when
you call the CLI directly.

### Direct CLI workflow

Use the CLI without the composite action:

```yaml
steps:
  - uses: actions/checkout@v4

  - uses: actions/setup-python@v5
    with:
      python-version: "3.13"

  - run: python -m pip install bc-lantern==0.8.0

  - run: bcl --version

  - name: Retrieve manifests
    env:
      GH_TOKEN: ${{ secrets.BC_LANTERN_TOKEN }}
    run: >-
      bcl app-json retrieve
      --owner my-organization
      --output app-json.json

  - name: Create reports
    run: >-
      bcl object-ranges report
      --app-json app-json.json
      --reference object_ranges.json
      --json-output object-range-report.json
      --markdown-output object-range-report.md

  - uses: actions/upload-artifact@v4
    with:
      name: object-range-report
      path: |
        object-range-report.json
        object-range-report.md
```

Skip the retrieval step when the workflow already provides `app-json.json`.

## PowerShell example

[`example.ps1`](example.ps1) collects manifests and creates several reports:

```powershell
.\example.ps1 `
  -Owner my-organization `
  -Reference C:\path\to\object_ranges.json
```

Generated aggregates and reports are ignored by Git. They can contain repository
metadata.

## Development

Install the project and its development tools:

```text
python -m pip install -e ".[dev]"
```

Run the tests:

```text
python -m pytest
```

Check the generated CLI reference:

```text
bcl docs sync --check
```

Use `bcl docs sync` after you change a command or option.

## Project information

- [CLI reference](docs/cli-reference.md)
- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [PyPI publishing guide](docs/publishing.md)
- [MIT License](LICENSE)