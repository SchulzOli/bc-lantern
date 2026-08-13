# BCCLI

BCCLI is a Python command-line tool for Microsoft Dynamics 365 Business Central
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

Use `pipx` to install BCCLI in an isolated environment:

```text
pipx install bccli
```

You can also use pip:

```text
python -m pip install bccli
```

Upgrade an existing installation:

```text
pipx upgrade bccli
```

### Install from GitHub

Install a specific release tag before or without a PyPI release:

```text
python -m pip install "bccli @ git+https://github.com/SchulzOli/BCCLI.git@v0.7.0"
```

Use a tag or full commit SHA in automated builds. Do not install from `main` in
a reproducible pipeline.

Verify the installation:

```text
bccli --help
```

## Quick start

### 1. Collect `app.json` manifests

Collect manifests from the repositories of the authenticated GitHub account:

```text
bccli app-json retrieve
```

Collect manifests from a specified user or organization:

```text
bccli app-json retrieve \
  --owner my-organization \
  --output app-json.json
```

BCCLI excludes archived repositories by default. Add `--include-archived` to
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
bccli object-ranges report \
  --app-json app-json.json \
  --reference object_ranges.json \
  --output object-range-report.json
```

Create a Markdown report:

```text
bccli object-ranges report \
  --reference object_ranges.json \
  --output object-range-report.md \
  --output-format markdown
```

`--app-json` defaults to `app-json.json`. The JSON output defaults to
`object-range-report.json`.

The report compares declared reservations. It does not scan AL source files for
implemented object IDs.

## Range filters

BCCLI classifies declared ranges with these Business Central categories:

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
bccli object-ranges report \
  --reference object_ranges.json \
  --hide-range-type rsp
```

Remove a category from all calculations:

```text
bccli object-ranges report \
  --reference object_ranges.json \
  --ignore-range-type customization
```

Both options are repeatable. Use `--conflict-range-type` to replace the default
set of conflict-enabled categories. By default, all categories except
`customization` participate in conflict detection.

See the [CLI reference](docs/cli-reference.md) for every command and option.

## Cache

BCCLI caches GitHub metadata and manifests by default:

```text
Windows: %LOCALAPPDATA%\bccli\cache
macOS:   ~/Library/Caches/bccli
Linux:   ${XDG_CACHE_HOME:-~/.cache}/bccli
```

Force a complete scan:

```text
bccli app-json retrieve --refresh
```

Disable the cache:

```text
bccli app-json retrieve --no-cache
```

Set another cache directory:

```text
bccli app-json retrieve --cache-dir path/to/cache
```

## Pipeline example

Pin the package version in a pipeline:

```yaml
steps:
  - uses: actions/checkout@v4

  - uses: actions/setup-python@v5
    with:
      python-version: "3.13"

  - run: python -m pip install bccli==0.7.0

  - run: >-
      bccli object-ranges report
      --app-json app-json.json
      --reference object_ranges.json
      --output object-range-report.json
```

The pipeline must provide `app-json.json` and `object_ranges.json`. Alternatively,
run `app-json retrieve` first and authenticate GitHub CLI in the pipeline.

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
bccli docs sync --check
```

Use `bccli docs sync` after you change a command or option.

## Project information

- [CLI reference](docs/cli-reference.md)
- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [PyPI publishing guide](docs/publishing.md)
- [MIT License](LICENSE)