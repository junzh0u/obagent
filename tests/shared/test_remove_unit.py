import json

from commands.remove import remove, remove_entry


def _setup_entry(vault, sha="abc123", **fields):
    """Create a vault entry with LLM JSON and rendered .md."""
    defaults = {"merchant": "ACME Store", "date": "2024-01-15", "total": "$42.50"}
    defaults.update(fields)
    target_dir = vault / "papers" / "_assets_" / sha
    for sub in ("src", "ocr", "llm"):
        (target_dir / sub).mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")
    (target_dir / "llm" / "default.json").write_text(json.dumps(defaults))

    title = f"{defaults['date']} - {defaults['merchant']} - {defaults['total']}"
    md_path = vault / "papers" / f"{title}.md"
    frontmatter = (
        f'---\nmerchant: "{defaults["merchant"]}"\n'
        f'date: "{defaults["date"]}"\ntotal: "{defaults["total"]}"\n---\n'
    )
    md_path.write_text(frontmatter + f"![[_assets_/{sha}/src/original.pdf#height]]\n")
    return target_dir, md_path


def test_remove_removes_md_and_dir(runner, vault):
    """Deleting an entry removes both the .md file and the data directory."""
    target_dir, md_path = _setup_entry(vault, sha="deadbeef")

    result = runner.invoke(
        remove,
        ["deadbeef"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert not md_path.exists()
    assert not target_dir.exists()


def test_remove_nonexistent_sha(runner, vault):
    """Deleting a nonexistent sha256 prints an error."""
    (vault / "papers" / "_assets_").mkdir(parents=True)

    result = runner.invoke(
        remove,
        ["nonexistent"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 1
    assert "Entry not found" in result.output


def test_remove_removes_embed_from_shared_md(runner, vault):
    """When .md has multiple embeds, only the matching embed line is removed."""
    _setup_entry(vault, sha="sha_a")
    target_dir_b, _ = _setup_entry(vault, sha="sha_b")

    # Manually create a shared .md with both embeds
    md_path = vault / "papers" / "2024-01-15 - ACME Store - $42.50.md"
    md_path.write_text(
        '---\nmerchant: "ACME Store"\ndate: "2024-01-15"\ntotal: "$42.50"\n---\n'
        "![[_assets_/sha_a/src/original.pdf#height]]\n"
        "![[_assets_/sha_b/src/original.pdf#height]]\n"
    )

    result = runner.invoke(
        remove,
        ["sha_b"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert md_path.exists()
    content = md_path.read_text()
    assert "sha_a" in content
    assert "sha_b" not in content
    assert not target_dir_b.exists()


def test_remove_no_md_still_removes_dir(runner, vault):
    """If no .md references the sha, the data directory is still removed."""
    target_dir = vault / "papers" / "_assets_" / "orphan"
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")

    result = runner.invoke(
        remove,
        ["orphan"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert not target_dir.exists()


def test_remove_by_note_path(runner, vault):
    """A full path to the note removes it and its data dir, same as its sha."""
    target_dir, md_path = _setup_entry(vault, sha="deadbeef")

    result = runner.invoke(
        remove,
        [str(md_path)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert not md_path.exists()
    assert not target_dir.exists()


def test_remove_by_note_filename(runner, vault):
    """A bare note filename is resolved inside the type dir."""
    target_dir, md_path = _setup_entry(vault, sha="deadbeef")

    result = runner.invoke(
        remove,
        [md_path.name],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert not md_path.exists()
    assert not target_dir.exists()


def test_remove_by_note_removes_all_embedded_sources(runner, vault):
    """A multi-embed note target removes every source it embeds."""
    target_dir_a, _ = _setup_entry(vault, sha="sha_a")
    target_dir_b, _ = _setup_entry(vault, sha="sha_b")
    md_path = vault / "papers" / "2024-01-15 - ACME Store - $42.50.md"
    md_path.write_text(
        '---\nmerchant: "ACME Store"\ndate: "2024-01-15"\ntotal: "$42.50"\n---\n'
        "![[_assets_/sha_a/src/original.pdf#height]]\n"
        "![[_assets_/sha_b/src/original.pdf#height]]\n"
    )

    result = runner.invoke(
        remove,
        [md_path.name],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert not md_path.exists()
    assert not target_dir_a.exists()
    assert not target_dir_b.exists()


def test_remove_missing_note_path_errors(runner, vault):
    """A .md target that doesn't exist is an error, not a sha lookup."""
    (vault / "papers" / "_assets_").mkdir(parents=True)

    result = runner.invoke(
        remove,
        ["no-such-note.md"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code != 0
    assert "Note not found" in result.output


def test_remove_entry_reports_and_removes(vault):
    """The pure helper removes the .md + data dir and reports what it touched."""
    target_dir, md_path = _setup_entry(vault, sha="deadbeef")
    result = remove_entry(vault / "papers", "deadbeef")
    assert result is not None
    assert result.notes == [(md_path.name, False)]  # note deleted, not just stripped
    assert result.data_dir == "deadbeef"
    assert not md_path.exists()
    assert not target_dir.exists()


def test_remove_entry_reports_stripped_embed(vault):
    """A note with another embed is kept and reported as stripped."""
    (vault / "papers" / "_assets_" / "sha_b" / "src").mkdir(parents=True)
    md_path = vault / "papers" / "shared.md"
    md_path.write_text(
        "---\n---\n![[_assets_/sha_a/src/original.pdf]]\n"
        "![[_assets_/sha_b/src/original.pdf]]\n"
    )
    result = remove_entry(vault / "papers", "sha_b")
    assert result is not None
    assert result.notes == [("shared.md", True)]  # kept (sha_a embed remains)
    assert md_path.exists()
    assert "sha_a" in md_path.read_text() and "sha_b" not in md_path.read_text()


def test_remove_entry_returns_none_for_missing(vault):
    """The pure helper reports None (and does nothing) for an unknown sha."""
    (vault / "papers" / "_assets_").mkdir(parents=True)
    assert remove_entry(vault / "papers", "nope") is None
