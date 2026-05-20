from pathlib import Path

import commands.bank_statement.pipeline  # noqa: F401 — triggers Pipeline registration
import commands.document.pipeline  # noqa: F401
import commands.receipt.pipeline  # noqa: F401

from commands.export import export_all


def _setup_entry(
    vault: Path,
    path: str,
    sha: str,
    src_name: str = "original.pdf",
    src_bytes: bytes = b"pdf-bytes",
) -> Path:
    src_dir = vault / path / "_assets_" / sha / "src"
    src_dir.mkdir(parents=True)
    (src_dir / src_name).write_bytes(src_bytes)
    return src_dir / src_name


def _write_note(vault: Path, path: str, stem: str, shas: list[str]) -> Path:
    note_dir = vault / path
    note_dir.mkdir(parents=True, exist_ok=True)
    md = note_dir / f"{stem}.md"
    embeds = "\n".join(f"![[_assets_/{sha}/src/original.pdf]]" for sha in shas)
    md.write_text(f"---\ntitle: {stem}\n---\n\n{embeds}\n")
    return md


def _invoke(runner, vault: Path, output_dir: Path):
    return runner.invoke(
        export_all,
        ["--output-dir", str(output_dir)],
        obj={"vault": str(vault)},
    )


def test_exports_every_type_in_one_invocation(runner, vault, tmp_path):
    """A single `obagent export` populates each type's subdir under output_dir."""
    _setup_entry(vault, "Documents", "sha-d", src_bytes=b"doc")
    _setup_entry(vault, "Receipts", "sha-r", src_bytes=b"receipt")
    _setup_entry(vault, "Bank Statements", "sha-b", src_bytes=b"statement")
    _write_note(vault, "Documents", "2024-01-15 - Tax Return", ["sha-d"])
    _write_note(vault, "Receipts", "2024-02-20 - Coffee", ["sha-r"])
    _write_note(vault, "Bank Statements", "2024-03-31 - Checking", ["sha-b"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (
        out / "Documents" / "2024" / "2024-01" / "2024-01-15 - Tax Return.pdf"
    ).read_bytes() == b"doc"
    assert (
        out / "Receipts" / "2024" / "2024-02" / "2024-02-20 - Coffee.pdf"
    ).read_bytes() == b"receipt"
    assert (
        out / "Bank Statements" / "2024" / "2024-03" / "2024-03-31 - Checking.pdf"
    ).read_bytes() == b"statement"


def test_prints_section_header_per_type(runner, vault, tmp_path):
    """Each type produces a `=== <Path> ===` banner in the output."""
    _setup_entry(vault, "Documents", "sha-d")
    _write_note(vault, "Documents", "2024-01-01 - Note", ["sha-d"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert "=== Documents ===" in result.output
    assert "=== Receipts ===" in result.output
    assert "=== Bank Statements ===" in result.output


def test_partial_vault_only_creates_populated_type_dirs(runner, vault, tmp_path):
    """Empty type subdirs are still created (mkdir parents=True), just empty."""
    _setup_entry(vault, "Documents", "sha-d", src_bytes=b"data")
    _write_note(vault, "Documents", "2024-04-04 - Only", ["sha-d"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (out / "Documents" / "2024" / "2024-04" / "2024-04-04 - Only.pdf").exists()
    # The other type roots are created (export_root.mkdir runs unconditionally)
    # but contain no exported files.
    assert (out / "Receipts").is_dir()
    assert list((out / "Receipts").iterdir()) == []
    assert (out / "Bank Statements").is_dir()
    assert list((out / "Bank Statements").iterdir()) == []


def test_env_var_provides_output_dir(runner, vault, tmp_path, monkeypatch):
    """OBAGENT_EXPORT env var is used when --output-dir is omitted."""
    _setup_entry(vault, "Receipts", "sha-r", src_bytes=b"data")
    _write_note(vault, "Receipts", "2024-05-05 - Coffee", ["sha-r"])
    out = tmp_path / "from-env"
    monkeypatch.setenv("OBAGENT_EXPORT", str(out))

    result = runner.invoke(export_all, [], obj={"vault": str(vault)})

    assert result.exit_code == 0, result.output
    assert (
        out / "Receipts" / "2024" / "2024-05" / "2024-05-05 - Coffee.pdf"
    ).read_bytes() == b"data"


def test_rerun_is_idempotent_across_all_types(runner, vault, tmp_path):
    """A second `obagent export` reports unchanged for every type's files."""
    _setup_entry(vault, "Documents", "sha-d", src_bytes=b"a")
    _setup_entry(vault, "Receipts", "sha-r", src_bytes=b"b")
    _setup_entry(vault, "Bank Statements", "sha-b", src_bytes=b"c")
    _write_note(vault, "Documents", "2024-06-06 - Doc", ["sha-d"])
    _write_note(vault, "Receipts", "2024-06-06 - Receipt", ["sha-r"])
    _write_note(vault, "Bank Statements", "2024-06-06 - Statement", ["sha-b"])
    out = tmp_path / "out"

    first = _invoke(runner, vault, out)
    assert first.exit_code == 0, first.output
    assert "1 exported" in first.output

    second = _invoke(runner, vault, out)
    assert second.exit_code == 0, second.output
    # Contract: nothing actually copied, every type seen, summaries unchanged.
    # We don't count exact occurrences because other tests in the suite can
    # add extra DocumentPipeline() instances to Pipeline._registry.
    assert "exported" not in second.output
    assert "1 unchanged" in second.output
    for type_path in ("Documents", "Receipts", "Bank Statements"):
        assert f"=== {type_path} ===" in second.output
