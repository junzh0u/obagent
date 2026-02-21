import json
import os
import time

from commands.render import render


def _setup_entry_with_llm(vault, sha="abc123", llm_filename="default.json", **fields):
    """Create a vault entry with LLM JSON ready for rendering."""
    defaults = {"merchant": "ACME Store", "date": "2024-01-15", "total": "$42.50"}
    defaults.update(fields)
    target_dir = vault / "papers" / "_assets_" / sha
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")
    (llm_dir / llm_filename).write_text(json.dumps(defaults))
    return target_dir


def test_md_created_with_frontmatter(runner, vault):
    """A <title>.md file is created with frontmatter and Obsidian embed link."""
    _setup_entry_with_llm(
        vault, sha="sha1", merchant="Coffee Shop", date="2024-06-01", total="$5.75"
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "2024-06-01 - Coffee Shop - $5.75.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert 'merchant: "Coffee Shop"' in content
    assert 'date: "2024-06-01"' in content
    assert 'total: "$5.75"' in content
    assert "![[_assets_/sha1/src/original.pdf#height]]" in content
    assert "Title: 2024-06-01 - Coffee Shop - $5.75" in result.output


def test_sanitizes_unsafe_characters(runner, vault):
    """Unsafe filename characters are stripped from the title."""
    _setup_entry_with_llm(
        vault, sha="sha2", merchant='Shop "A"/B', date="2024-01-15", total="$10.00"
    )

    runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    md_file = vault / "papers" / "2024-01-15 - Shop AB - $10.00.md"
    assert md_file.exists()
    assert "![[_assets_/sha2/src/original.pdf#height]]" in md_file.read_text()


def test_skip_existing_md(runner, vault):
    """Rendering is skipped when .md file already exists."""
    _setup_entry_with_llm(vault, sha="sha3")
    # Place existing .md at vault/papers/ level with the title that would be generated
    (vault / "papers" / "2024-01-15 - ACME Store - $42.50.md").write_text(
        "---\nold: true\n---\n"
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "already exists, skipping" in result.output


def test_overwrite_replaces_md(runner, vault):
    """With --overwrite, old .md files are deleted and new one is created."""
    _setup_entry_with_llm(
        vault, sha="sha4", merchant="New Shop", date="2025-01-01", total="$99.00"
    )
    papers_dir = vault / "papers"
    (papers_dir / "old title.md").write_text("---\nold: true\n---\n")

    result = runner.invoke(
        render,
        ["--overwrite"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert not (papers_dir / "old title.md").exists()
    new_md = papers_dir / "2025-01-01 - New Shop - $99.00.md"
    assert new_md.exists()
    content = new_md.read_text()
    assert 'merchant: "New Shop"' in content


def test_no_llm_json_no_entries(runner, vault):
    """Without llm JSON, no entries are processed."""
    (vault / "papers" / "_assets_" / "sha5").mkdir(parents=True)

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Title:" not in result.output


def test_render_picks_newest_llm_json(runner, vault):
    """When multiple LLM json files exist, the newest by mtime is used."""
    target_dir = vault / "papers" / "_assets_" / "sha6"
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")

    old_file = llm_dir / "old-model.json"
    old_file.write_text(
        json.dumps({"merchant": "Old Shop", "date": "2024-01-01", "total": "$1.00"})
    )
    old_mtime = time.time() - 100
    os.utime(old_file, (old_mtime, old_mtime))

    new_file = llm_dir / "new-model.json"
    new_file.write_text(
        json.dumps({"merchant": "New Shop", "date": "2025-06-01", "total": "$99.00"})
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Title: 2025-06-01 - New Shop - $99.00" in result.output
    assert (vault / "papers" / "2025-06-01 - New Shop - $99.00.md").exists()
