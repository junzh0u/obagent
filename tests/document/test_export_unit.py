from pathlib import Path

from commands.document.export import export


def _setup_entry(
    vault: Path,
    sha: str,
    src_name: str = "original.pdf",
    src_bytes: bytes = b"pdf-bytes",
) -> Path:
    """Create a vault entry with a source file under _assets_/{sha}/src/."""
    src_dir = vault / "docs" / "_assets_" / sha / "src"
    src_dir.mkdir(parents=True)
    (src_dir / src_name).write_bytes(src_bytes)
    return src_dir / src_name


def _write_note(vault: Path, stem: str, shas: list[str], suffix: str = "pdf") -> Path:
    """Write a .md note that embeds one or more shas."""
    note_dir = vault / "docs"
    note_dir.mkdir(parents=True, exist_ok=True)
    md = note_dir / f"{stem}.md"
    embeds = "\n".join(f"![[_assets_/{sha}/src/original.{suffix}]]" for sha in shas)
    md.write_text(f"---\ntitle: {stem}\n---\n\n{embeds}\n")
    return md


def _invoke(runner, vault: Path, output_dir: Path):
    return runner.invoke(
        export,
        ["--output-dir", str(output_dir)],
        obj={"vault": str(vault), "path": "docs"},
    )


def test_happy_path_groups_by_year_and_month(runner, vault, tmp_path):
    """Notes land in output_dir/YYYY/YYYY-MM/ based on filename date prefix."""
    _setup_entry(vault, "sha1", src_bytes=b"first")
    _setup_entry(vault, "sha2", src_bytes=b"second")
    _write_note(vault, "2024-01-01 - Note One", ["sha1"])
    _write_note(vault, "2024-02-02 - Note Two", ["sha2"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (out / "2024" / "2024-01" / "2024-01-01 - Note One.pdf").read_bytes() == (
        b"first"
    )
    assert (out / "2024" / "2024-02" / "2024-02-02 - Note Two.pdf").read_bytes() == (
        b"second"
    )


def test_different_years_get_separate_year_folders(runner, vault, tmp_path):
    """A 2024 note and a 2025 note land under different YYYY folders."""
    _setup_entry(vault, "sha1", src_bytes=b"old")
    _setup_entry(vault, "sha2", src_bytes=b"new")
    _write_note(vault, "2024-12-31 - End", ["sha1"])
    _write_note(vault, "2025-01-01 - Start", ["sha2"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (out / "2024" / "2024-12" / "2024-12-31 - End.pdf").exists()
    assert (out / "2025" / "2025-01" / "2025-01-01 - Start.pdf").exists()


def test_undated_note_goes_to_undated_folder(runner, vault, tmp_path):
    """A note without a YYYY-MM prefix lands in output_dir/undated/."""
    _setup_entry(vault, "sha1", src_bytes=b"data")
    _write_note(vault, "No Date Here", ["sha1"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (out / "undated" / "No Date Here.pdf").read_bytes() == b"data"


def test_multi_embed_uses_sha_suffix_for_extras(runner, vault, tmp_path):
    """A note with two embeds: first plain, second suffixed with sha12, same bucket."""
    sha1 = "a" * 64
    sha2 = "b" * 64
    _setup_entry(vault, sha1, src_bytes=b"primary")
    _setup_entry(vault, sha2, src_bytes=b"secondary")
    _write_note(vault, "2024-03-15 - Combined", [sha1, sha2])
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    bucket = out / "2024" / "2024-03"
    assert (bucket / "2024-03-15 - Combined.pdf").read_bytes() == b"primary"
    assert (bucket / f"2024-03-15 - Combined-{sha2[:12]}.pdf").read_bytes() == (
        b"secondary"
    )


def test_jpg_extension_preserved(runner, vault, tmp_path):
    """A .jpg source produces a .jpg output file."""
    src_dir = vault / "docs" / "_assets_" / "sha-jpg" / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "original.jpg").write_bytes(b"jpg-bytes")
    md = vault / "docs" / "2024-06-01 - Photo Note.md"
    md.write_text("![[_assets_/sha-jpg/src/original.jpg]]\n")
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (out / "2024" / "2024-06" / "2024-06-01 - Photo Note.jpg").read_bytes() == (
        b"jpg-bytes"
    )


def test_missing_source_is_skipped_with_warning(runner, vault, tmp_path):
    """A .md referencing a sha with no src/original.* logs a warning, no crash."""
    _write_note(vault, "2024-01-15 - Orphan Note", ["dangling-sha"])
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert "Missing source" in result.output
    assert not (out / "2024" / "2024-01" / "2024-01-15 - Orphan Note.pdf").exists()


def test_overwrites_existing_destination_file(runner, vault, tmp_path):
    """Stale content at the destination is replaced by the current source."""
    _setup_entry(vault, "sha1", src_bytes=b"fresh")
    _write_note(vault, "2024-04-04 - Note", ["sha1"])
    out = tmp_path / "out"
    bucket = out / "2024" / "2024-04"
    bucket.mkdir(parents=True)
    (bucket / "2024-04-04 - Note.pdf").write_bytes(b"stale")

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (bucket / "2024-04-04 - Note.pdf").read_bytes() == b"fresh"


def test_creates_output_dir_with_parents(runner, vault, tmp_path):
    """Nested non-existent output paths (and bucket subdirs) are created."""
    _setup_entry(vault, "sha1")
    _write_note(vault, "2024-05-01 - Note", ["sha1"])
    out = tmp_path / "deeply" / "nested" / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (out / "2024" / "2024-05" / "2024-05-01 - Note.pdf").exists()


def test_empty_vault_runs_cleanly(runner, vault, tmp_path):
    """No notes, no embeds: command exits 0 with no output files."""
    (vault / "docs").mkdir()
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert list(out.iterdir()) == []


def test_dangling_files_removed_within_managed_subdirs(runner, vault, tmp_path):
    """Stale files inside YYYY/YYYY-MM/ and undated/ are removed; other subdirs untouched."""
    _setup_entry(vault, "sha1", src_bytes=b"current")
    _write_note(vault, "2024-07-07 - Keep Me", ["sha1"])
    out = tmp_path / "out"
    out.mkdir()

    # Stale file in the right bucket (same as the live note's bucket)
    bucket = out / "2024" / "2024-07"
    bucket.mkdir(parents=True)
    (bucket / "2024-07-01 - Stale.pdf").write_bytes(b"old")

    # Stale file in a bucket no live note touches
    abandoned = out / "2023" / "2023-12"
    abandoned.mkdir(parents=True)
    (abandoned / "2023-12-31 - Abandoned.pdf").write_bytes(b"old")

    # Stale file in undated/
    undated = out / "undated"
    undated.mkdir()
    (undated / "Forgotten.pdf").write_bytes(b"old")

    # Legacy top-level file from the old flat layout
    (out / "legacy.pdf").write_bytes(b"old")

    # Unrelated sibling subdir — must be left alone
    sibling = out / "keep-me"
    sibling.mkdir()
    (sibling / "child.pdf").write_bytes(b"untouched")

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (bucket / "2024-07-07 - Keep Me.pdf").read_bytes() == b"current"
    # Stale file in live bucket removed
    assert not (bucket / "2024-07-01 - Stale.pdf").exists()
    # Stale file in abandoned bucket removed; bucket pruned
    assert not abandoned.exists()
    assert not (out / "2023").exists()
    # Stale undated file removed; undated/ pruned
    assert not undated.exists()
    # Legacy top-level file removed
    assert not (out / "legacy.pdf").exists()
    # Unrelated subdir untouched
    assert (sibling / "child.pdf").read_bytes() == b"untouched"


def test_env_var_provides_output_dir(runner, vault, tmp_path, monkeypatch):
    """OBAGENT_DOCUMENT_EXPORT env var is used when --output-dir is omitted."""
    _setup_entry(vault, "sha1", src_bytes=b"data")
    _write_note(vault, "2024-08-08 - Note", ["sha1"])
    out = tmp_path / "from-env"
    monkeypatch.setenv("OBAGENT_DOCUMENT_EXPORT", str(out))

    result = runner.invoke(
        export,
        [],
        obj={"vault": str(vault), "path": "docs"},
    )

    assert result.exit_code == 0, result.output
    assert (out / "2024" / "2024-08" / "2024-08-08 - Note.pdf").read_bytes() == b"data"


def test_note_without_embeds_is_ignored(runner, vault, tmp_path):
    """A .md with no embed links is skipped silently."""
    _setup_entry(vault, "sha1")
    _write_note(vault, "2024-09-09 - Has Embed", ["sha1"])
    plain = vault / "docs" / "2024-10-10 - Plain Note.md"
    plain.write_text("---\ntitle: Plain\n---\n\nJust text, no embed.\n")
    out = tmp_path / "out"

    result = _invoke(runner, vault, out)

    assert result.exit_code == 0, result.output
    assert (out / "2024" / "2024-09" / "2024-09-09 - Has Embed.pdf").exists()
    assert not (out / "2024" / "2024-10").exists()
