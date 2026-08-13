from __future__ import annotations

from pathlib import Path

from bc_lantern.cli import build_parser, main
from bc_lantern.cli_docs import render_cli_reference


def test_rendered_reference_contains_every_command_and_filter_option() -> None:
    document = render_cli_reference()

    assert "# BC Lantern command reference" in document
    assert str(Path.home()) not in document
    assert "## `bcl app-json retrieve`" in document
    assert "`--include-archived`" in document
    assert "## `bcl object-ranges report`" in document
    assert "`--hide-range-type TYPE`" in document
    assert "`--ignore-range-type TYPE`" in document
    assert "`--conflict-range-type TYPE`" in document
    assert "## `bcl docs sync`" in document
    assert "`--check`" in document


def test_reference_wrapping_does_not_depend_on_terminal_width(
    monkeypatch: object,
) -> None:
    monkeypatch.setenv("COLUMNS", "60")  # type: ignore[attr-defined]
    narrow = render_cli_reference(build_parser())
    monkeypatch.setenv("COLUMNS", "140")  # type: ignore[attr-defined]
    wide = render_cli_reference(build_parser())

    assert narrow == wide


def test_docs_sync_writes_and_checks_generated_reference(tmp_path: Path) -> None:
    output = tmp_path / "cli-reference.md"

    assert main(["docs", "sync", "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == render_cli_reference()
    assert main(["docs", "sync", "--output", str(output), "--check"]) == 0

    output.write_text("stale\n", encoding="utf-8")

    assert main(["docs", "sync", "--output", str(output), "--check"]) == 1
