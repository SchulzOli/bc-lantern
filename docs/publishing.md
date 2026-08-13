# Publishing BCCLI to PyPI

BCCLI uses PyPI Trusted Publishing through GitHub Actions. No PyPI API token is
stored in GitHub.

## One-time setup

1. Make `SchulzOli/BCCLI` public on GitHub.
2. Create a PyPI account, verify its email address, and enable two-factor
   authentication.
3. In the GitHub repository, open **Settings > Environments**, create an
   environment named `pypi`, and add any required-reviewer or protected-tag
   rules you want for releases.
4. In PyPI account settings, open **Publishing** and add a pending GitHub
   publisher with these values:

| Field | Value |
|---|---|
| PyPI project name | `bccli` |
| GitHub owner | `SchulzOli` |
| GitHub repository | `BCCLI` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

The pending publisher does not reserve the name. PyPI creates the project when
the workflow publishes successfully for the first time.

## Create a release

1. Set the new version in `pyproject.toml`.
2. Run the release checks:

   ```text
   python -m pip install -e ".[dev]"
   python -m pytest
   bccli docs sync --check
   python -m build
   python -m twine check dist/*
   ```

3. Commit and push the version change.
4. Create and push a matching tag:

   ```text
   git tag -a v0.7.0 -m "BCCLI 0.7.0"
   git push origin v0.7.0
   ```

The `Release to PyPI` workflow verifies that `v0.7.0` matches version `0.7.0`,
runs the tests, builds and checks both distributions, tests the wheel, and then
publishes through OpenID Connect. PyPI versions are immutable; increment the
version before retrying after any successful upload.

## Use the package in a pipeline

Pin the released version for reproducible builds:

```text
python -m pip install bccli==0.7.0
bccli --help
```

## References

- [Creating a PyPI project with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
- [Packaging Python projects](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
- [PyPI publish GitHub Action](https://github.com/pypa/gh-action-pypi-publish)