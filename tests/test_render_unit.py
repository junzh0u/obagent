import json
import os
import time

from commands.render import render


def _setup_entry_with_llm(
    vault,
    sha="abc123",
    llm_filename="default.json",
    src_filename="original.pdf",
    **fields,
):
    """Create a vault entry with LLM JSON ready for rendering."""
    defaults = {"merchant": "ACME Store", "date": "2024-01-15", "total": "$42.50"}
    defaults.update(fields)
    target_dir = vault / "papers" / "_assets_" / sha
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / src_filename).write_bytes(b"test")
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
    assert "![[_assets_/sha1/src/metadata.json]]" in content
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
    content = md_file.read_text()
    assert "![[_assets_/sha2/src/original.pdf#height]]" in content
    assert "![[_assets_/sha2/src/metadata.json]]" in content


def test_null_total_defaults_to_zero(runner, vault):
    """When total is null, $0.00 is used instead."""
    _setup_entry_with_llm(
        vault, sha="sha_null", merchant="Free Store", date="2024-01-15"
    )
    # Overwrite the JSON with null total
    import json

    llm_json = vault / "papers" / "_assets_" / "sha_null" / "llm" / "default.json"
    llm_json.write_text(
        json.dumps({"merchant": "Free Store", "date": "2024-01-15", "total": None})
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "2024-01-15 - Free Store - $0.00.md"
    assert md_file.exists()
    assert 'total: "$0.00"' in md_file.read_text()


def test_null_date_defaults_to_empty(runner, vault):
    """When date is null, it is omitted from the title."""
    _setup_entry_with_llm(vault, sha="sha_nodate", merchant="Mystery Shop")
    import json

    llm_json = vault / "papers" / "_assets_" / "sha_nodate" / "llm" / "default.json"
    llm_json.write_text(
        json.dumps({"merchant": "Mystery Shop", "date": None, "total": "$10.00"})
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "Mystery Shop - $10.00.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert 'date: ""' in content


def test_skip_existing_md(runner, vault):
    """Rendering is skipped when .md already references this sha256."""
    _setup_entry_with_llm(vault, sha="sha3")
    # Place existing .md that already references sha3
    (vault / "papers" / "2024-01-15 - ACME Store - $42.50.md").write_text(
        "---\nold: true\n---\n![[_assets_/sha3/src/original.pdf#height]]\n"
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "already exists, skipping" in result.output


def test_append_different_sha(runner, vault):
    """When .md exists but for a different sha256, the new PDF embed is appended."""
    _setup_entry_with_llm(vault, sha="sha3a")
    _setup_entry_with_llm(vault, sha="sha3b")
    md_path = vault / "papers" / "2024-01-15 - ACME Store - $42.50.md"

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    content = md_path.read_text()
    assert "![[_assets_/sha3a/src/original.pdf#height]]" in content
    assert "![[_assets_/sha3a/src/metadata.json]]" in content
    assert "![[_assets_/sha3b/src/original.pdf#height]]" in content
    assert "![[_assets_/sha3b/src/metadata.json]]" in content
    assert "Appended to:" in result.output


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


def test_overwrite_single_sha_deletes_old_md(runner, vault):
    """With --overwrite and sha256, the old .md referencing that sha is deleted first."""
    _setup_entry_with_llm(
        vault, sha="sha_ow", merchant="Old Name", date="2024-01-15", total="$42.50"
    )
    # Simulate an existing .md with old title referencing this sha
    old_md = vault / "papers" / "2024-01-15 - Old Name - $42.50.md"
    old_md.write_text(
        '---\nmerchant: "Old Name"\n---\n![[_assets_/sha_ow/src/original.pdf#height]]\n'
    )
    # Now update the LLM JSON to produce a different title
    import json

    llm_json = vault / "papers" / "_assets_" / "sha_ow" / "llm" / "default.json"
    llm_json.write_text(
        json.dumps({"merchant": "New Name", "date": "2024-01-15", "total": "$42.50"})
    )

    result = runner.invoke(
        render,
        ["--overwrite", "sha_ow"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert not old_md.exists()
    new_md = vault / "papers" / "2024-01-15 - New Name - $42.50.md"
    assert new_md.exists()


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


def test_render_single_sha256(runner, vault):
    """When sha256 argument is given, only that entry is rendered."""
    _setup_entry_with_llm(
        vault, sha="target", merchant="Target Shop", date="2024-03-01", total="$20.00"
    )
    _setup_entry_with_llm(
        vault, sha="other", merchant="Other Shop", date="2024-04-01", total="$30.00"
    )

    result = runner.invoke(
        render,
        ["target"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert (vault / "papers" / "2024-03-01 - Target Shop - $20.00.md").exists()
    assert not (vault / "papers" / "2024-04-01 - Other Shop - $30.00.md").exists()


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


def test_render_jpeg_embed(runner, vault):
    """JPEG source file produces an embed with original.jpg."""
    _setup_entry_with_llm(
        vault,
        sha="jpgsha",
        src_filename="original.jpg",
        merchant="Photo Shop",
        date="2024-07-01",
        total="$15.00",
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "2024-07-01 - Photo Shop - $15.00.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "![[_assets_/jpgsha/src/original.jpg]]" in content
    assert "![[_assets_/jpgsha/src/metadata.json]]" in content
