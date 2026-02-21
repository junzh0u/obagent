import json

from commands.remove import remove


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
