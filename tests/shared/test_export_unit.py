from pathlib import Path

import pytest

from commands.export import export

# Run every test against both real type subdirs to confirm the same command
# works whether the parent group sets path="Documents" or path="Receipts".
TYPES = ["Documents", "Receipts"]


def _setup_entry(
    vault: Path,
    path: str,
    sha: str,
    src_name: str = "original.pdf",
    src_bytes: bytes = b"pdf-bytes",
) -> Path:
    """Create a vault entry with a source file under _assets_/{sha}/src/."""
    src_dir = vault / path / "_assets_" / sha / "src"
    src_dir.mkdir(parents=True)
    (src_dir / src_name).write_bytes(src_bytes)
    return src_dir / src_name


def _write_note(
    vault: Path, path: str, stem: str, shas: list[str], suffix: str = "pdf"
) -> Path:
    """Write a .md note that embeds one or more shas."""
    note_dir = vault / path
    note_dir.mkdir(parents=True, exist_ok=True)
    md = note_dir / f"{stem}.md"
    embeds = "\n".join(f"![[_assets_/{sha}/src/original.{suffix}]]" for sha in shas)
    md.write_text(f"---\ntitle: {stem}\n---\n\n{embeds}\n")
    return md


def _invoke(runner, vault: Path, path: str, output_dir: Path):
    return runner.invoke(
        export,
        ["--output-dir", str(output_dir)],
        obj={"vault": str(vault), "path": path},
    )


@pytest.mark.parametrize("path", TYPES)
def test_happy_path_groups_by_year_and_month(runner, vault, tmp_path, path):
    """Notes land in output_dir/{path}/YYYY/YYYY-MM/ based on filename date prefix."""
    _setup_entry(vault, path, "sha1", src_bytes=b"first")
    _setup_entry(vault, path, "sha2", src_bytes=b"second")
    _write_note(vault, path, "2024-01-01 - Note One", ["sha1"])
    _write_note(vault, path, "2024-02-02 - Note Two", ["sha2"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert (
        out / path / "2024" / "2024-01" / "2024-01-01 - Note One.pdf"
    ).read_bytes() == b"first"
    assert (
        out / path / "2024" / "2024-02" / "2024-02-02 - Note Two.pdf"
    ).read_bytes() == b"second"


@pytest.mark.parametrize("path", TYPES)
def test_different_years_get_separate_year_folders(runner, vault, tmp_path, path):
    """A 2024 note and a 2025 note land under different YYYY folders."""
    _setup_entry(vault, path, "sha1", src_bytes=b"old")
    _setup_entry(vault, path, "sha2", src_bytes=b"new")
    _write_note(vault, path, "2024-12-31 - End", ["sha1"])
    _write_note(vault, path, "2025-01-01 - Start", ["sha2"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert (out / path / "2024" / "2024-12" / "2024-12-31 - End.pdf").exists()
    assert (out / path / "2025" / "2025-01" / "2025-01-01 - Start.pdf").exists()


@pytest.mark.parametrize("path", TYPES)
def test_undated_note_goes_to_undated_folder(runner, vault, tmp_path, path):
    """A note without a YYYY-MM prefix lands in output_dir/{path}/undated/."""
    _setup_entry(vault, path, "sha1", src_bytes=b"data")
    _write_note(vault, path, "No Date Here", ["sha1"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert (out / path / "undated" / "No Date Here.pdf").read_bytes() == b"data"


@pytest.mark.parametrize("path", TYPES)
def test_multi_embed_uses_sha_suffix_for_extras(runner, vault, tmp_path, path):
    """A note with two embeds: first plain, second suffixed with sha12, same bucket."""
    sha1 = "a" * 64
    sha2 = "b" * 64
    _setup_entry(vault, path, sha1, src_bytes=b"primary")
    _setup_entry(vault, path, sha2, src_bytes=b"secondary")
    _write_note(vault, path, "2024-03-15 - Combined", [sha1, sha2])
    out = tmp_path / "out"

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    bucket = out / path / "2024" / "2024-03"
    assert (bucket / "2024-03-15 - Combined.pdf").read_bytes() == b"primary"
    assert (
        bucket / f"2024-03-15 - Combined-{sha2[:12]}.pdf"
    ).read_bytes() == b"secondary"


@pytest.mark.parametrize("path", TYPES)
def test_jpg_extension_preserved(runner, vault, tmp_path, path):
    """A .jpg source produces a .jpg output file."""
    src_dir = vault / path / "_assets_" / "sha-jpg" / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "original.jpg").write_bytes(b"jpg-bytes")
    md = vault / path / "2024-06-01 - Photo Note.md"
    md.write_text("![[_assets_/sha-jpg/src/original.jpg]]\n")
    out = tmp_path / "out"

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert (
        out / path / "2024" / "2024-06" / "2024-06-01 - Photo Note.jpg"
    ).read_bytes() == b"jpg-bytes"


@pytest.mark.parametrize("path", TYPES)
def test_missing_source_is_skipped_with_warning(runner, vault, tmp_path, path):
    """A .md referencing a sha with no src/original.* logs a warning, no crash."""
    _write_note(vault, path, "2024-01-15 - Orphan Note", ["dangling-sha"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert "Missing source" in result.output
    assert not (
        out / path / "2024" / "2024-01" / "2024-01-15 - Orphan Note.pdf"
    ).exists()


@pytest.mark.parametrize("path", TYPES)
def test_overwrites_existing_destination_file(runner, vault, tmp_path, path):
    """Stale content at the destination is replaced by the current source."""
    _setup_entry(vault, path, "sha1", src_bytes=b"fresh")
    _write_note(vault, path, "2024-04-04 - Note", ["sha1"])
    out = tmp_path / "out"
    bucket = out / path / "2024" / "2024-04"
    bucket.mkdir(parents=True)
    (bucket / "2024-04-04 - Note.pdf").write_bytes(b"stale")

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert (bucket / "2024-04-04 - Note.pdf").read_bytes() == b"fresh"


@pytest.mark.parametrize("path", TYPES)
def test_creates_output_dir_with_parents(runner, vault, tmp_path, path):
    """Nested non-existent output paths (and bucket subdirs) are created."""
    _setup_entry(vault, path, "sha1")
    _write_note(vault, path, "2024-05-01 - Note", ["sha1"])
    out = tmp_path / "deeply" / "nested" / "out"

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert (out / path / "2024" / "2024-05" / "2024-05-01 - Note.pdf").exists()


@pytest.mark.parametrize("path", TYPES)
def test_empty_vault_runs_cleanly(runner, vault, tmp_path, path):
    """No notes, no embeds: command creates {path}/ but writes nothing inside."""
    (vault / path).mkdir()
    out = tmp_path / "out"

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert list((out / path).iterdir()) == []


@pytest.mark.parametrize("path", TYPES)
def test_dangling_files_removed_within_managed_subdirs(runner, vault, tmp_path, path):
    """Stale files inside {path}/YYYY/YYYY-MM/ and {path}/undated/ are removed."""
    _setup_entry(vault, path, "sha1", src_bytes=b"current")
    _write_note(vault, path, "2024-07-07 - Keep Me", ["sha1"])
    out = tmp_path / "out"
    type_root = out / path
    type_root.mkdir(parents=True)

    # Stale file in the right bucket (same as the live note's bucket)
    bucket = type_root / "2024" / "2024-07"
    bucket.mkdir(parents=True)
    (bucket / "2024-07-01 - Stale.pdf").write_bytes(b"old")

    # Stale file in a bucket no live note touches
    abandoned = type_root / "2023" / "2023-12"
    abandoned.mkdir(parents=True)
    (abandoned / "2023-12-31 - Abandoned.pdf").write_bytes(b"old")

    # Stale file in undated/
    undated = type_root / "undated"
    undated.mkdir()
    (undated / "Forgotten.pdf").write_bytes(b"old")

    # Legacy top-level file (e.g. from the prior flat layout)
    (type_root / "legacy.pdf").write_bytes(b"old")

    # Unrelated sibling subdir inside the type root — must be left alone
    sibling = type_root / "keep-me"
    sibling.mkdir()
    (sibling / "child.pdf").write_bytes(b"untouched")

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert (bucket / "2024-07-07 - Keep Me.pdf").read_bytes() == b"current"
    assert not (bucket / "2024-07-01 - Stale.pdf").exists()
    assert not abandoned.exists()
    assert not (type_root / "2023").exists()
    assert not undated.exists()
    assert not (type_root / "legacy.pdf").exists()
    assert (sibling / "child.pdf").read_bytes() == b"untouched"


@pytest.mark.parametrize("path", TYPES)
def test_env_var_provides_output_dir(runner, vault, tmp_path, monkeypatch, path):
    """OBAGENT_EXPORT env var is used when --output-dir is omitted."""
    _setup_entry(vault, path, "sha1", src_bytes=b"data")
    _write_note(vault, path, "2024-08-08 - Note", ["sha1"])
    out = tmp_path / "from-env"
    monkeypatch.setenv("OBAGENT_EXPORT", str(out))

    result = runner.invoke(
        export,
        [],
        obj={"vault": str(vault), "path": path},
    )

    assert result.exit_code == 0, result.output
    assert (
        out / path / "2024" / "2024-08" / "2024-08-08 - Note.pdf"
    ).read_bytes() == b"data"


@pytest.mark.parametrize("path", TYPES)
def test_note_without_embeds_is_ignored(runner, vault, tmp_path, path):
    """A .md with no embed links is skipped silently."""
    _setup_entry(vault, path, "sha1")
    _write_note(vault, path, "2024-09-09 - Has Embed", ["sha1"])
    plain = vault / path / "2024-10-10 - Plain Note.md"
    plain.write_text("---\ntitle: Plain\n---\n\nJust text, no embed.\n")
    out = tmp_path / "out"

    result = _invoke(runner, vault, path, out)

    assert result.exit_code == 0, result.output
    assert (out / path / "2024" / "2024-09" / "2024-09-09 - Has Embed.pdf").exists()
    assert not (out / path / "2024" / "2024-10").exists()


def test_cross_type_isolation(runner, vault, tmp_path):
    """Running export for one type does not touch files written by another type."""
    _setup_entry(vault, "Documents", "sha-d", src_bytes=b"doc-data")
    _setup_entry(vault, "Receipts", "sha-r", src_bytes=b"receipt-data")
    _write_note(vault, "Documents", "2024-01-01 - Doc", ["sha-d"])
    _write_note(vault, "Receipts", "2024-01-01 - Receipt", ["sha-r"])
    out = tmp_path / "out"

    # Export documents first, then receipts.
    doc_result = _invoke(runner, vault, "Documents", out)
    assert doc_result.exit_code == 0, doc_result.output
    doc_pdf = out / "Documents" / "2024" / "2024-01" / "2024-01-01 - Doc.pdf"
    assert doc_pdf.read_bytes() == b"doc-data"

    receipt_result = _invoke(runner, vault, "Receipts", out)
    assert receipt_result.exit_code == 0, receipt_result.output
    receipt_pdf = out / "Receipts" / "2024" / "2024-01" / "2024-01-01 - Receipt.pdf"
    assert receipt_pdf.read_bytes() == b"receipt-data"

    # Documents files still intact after the receipts run.
    assert doc_pdf.read_bytes() == b"doc-data"

    # Re-running documents must not nuke receipts.
    doc_rerun = _invoke(runner, vault, "Documents", out)
    assert doc_rerun.exit_code == 0, doc_rerun.output
    assert receipt_pdf.read_bytes() == b"receipt-data"
