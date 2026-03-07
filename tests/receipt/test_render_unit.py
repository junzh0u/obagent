import json
import os
import time

from commands.receipt.pipeline import receipt_pipeline


def _setup_entry_with_llm(
    vault,
    sha="abc123",
    llm_filename="default.json",
    src_filename="original.pdf",
    consumed_at="2024-06-01T12:00:00+00:00",
    **fields,
):
    """Create a vault entry with LLM JSON ready for rendering."""
    defaults = {"merchant": "ACME Store", "date": "2024-01-15", "total": "$42.50"}
    defaults.update(fields)
    target_dir = vault / "papers" / "_assets_" / sha
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True, exist_ok=True)
    (target_dir / "src" / src_filename).write_bytes(b"test")
    (target_dir / "src" / "metadata.json").write_text(
        json.dumps(
            {
                "original_filepath": "/test/path",
                "sha256": sha,
                "consumed_at": consumed_at,
            }
        )
    )
    (llm_dir / llm_filename).write_text(json.dumps(defaults))
    return target_dir


def test_md_created_with_frontmatter(runner, vault):
    """A <title>.md file is created with frontmatter and Obsidian embed link."""
    _setup_entry_with_llm(
        vault, sha="sha1", merchant="Coffee Shop", date="2024-06-01", total="$5.75"
    )

    result = runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "2024-06-01 - Coffee Shop - $5.75.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "merchant: Coffee Shop" in content
    assert "date: 2024-06-01" in content
    assert "total: $5.75" in content
    assert "consumed_at: 2024-06-01T12:00:00+00:00" in content
    assert "![[_assets_/sha1/src/original.pdf#height]]" in content
    assert "![[_assets_/sha1/src/metadata.json]]" in content
    assert "Created: 2024-06-01 - Coffee Shop - $5.75" in result.output


def test_prompt_in_json_excluded_from_frontmatter(runner, vault):
    """A 'prompt' key in the LLM JSON is not rendered into frontmatter."""
    target_dir = _setup_entry_with_llm(
        vault, sha="sha_pp", merchant="Shop", date="2024-01-01", total="$5.00"
    )
    # Add a prompt key to the JSON (as the llm command now does)
    llm_json = target_dir / "llm" / "default.json"
    data = json.loads(llm_json.read_text())
    data["prompt"] = "Extract the following fields..."
    llm_json.write_text(json.dumps(data))

    result = runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "2024-01-01 - Shop - $5.00.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "prompt" not in content


def test_sanitizes_unsafe_characters(runner, vault):
    """Unsafe filename characters are stripped from the title."""
    _setup_entry_with_llm(
        vault, sha="sha2", merchant='Shop "A"/B', date="2024-01-15", total="$10.00"
    )

    runner.invoke(
        receipt_pipeline.render_command,
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
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "2024-01-15 - Free Store - $0.00.md"
    assert md_file.exists()
    assert "total: $0.00" in md_file.read_text()


def test_null_date_defaults_to_empty(runner, vault):
    """When date is null, it is omitted from the title."""
    _setup_entry_with_llm(vault, sha="sha_nodate", merchant="Mystery Shop")
    import json

    llm_json = vault / "papers" / "_assets_" / "sha_nodate" / "llm" / "default.json"
    llm_json.write_text(
        json.dumps({"merchant": "Mystery Shop", "date": None, "total": "$10.00"})
    )

    result = runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "Mystery Shop - $10.00.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "date: " in content


def test_append_different_sha(runner, vault):
    """When .md exists but for a different sha256, the new PDF embed is appended."""
    _setup_entry_with_llm(vault, sha="sha3a")
    _setup_entry_with_llm(vault, sha="sha3b")
    md_path = vault / "papers" / "2024-01-15 - ACME Store - $42.50.md"

    result = runner.invoke(
        receipt_pipeline.render_command,
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


def test_render_replaces_old_notes(runner, vault):
    """All .md files are cleared upfront and re-rendered."""
    _setup_entry_with_llm(
        vault, sha="sha4", merchant="New Shop", date="2025-01-01", total="$99.00"
    )
    papers_dir = vault / "papers"
    (papers_dir / "old title.md").write_text("---\nold: true\n---\n")

    result = runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert not (papers_dir / "old title.md").exists()
    assert "Removed: old title.md" in result.output
    new_md = papers_dir / "2025-01-01 - New Shop - $99.00.md"
    assert new_md.exists()
    content = new_md.read_text()
    assert "merchant: New Shop" in content


def test_rerender_unchanged_shows_stats(runner, vault):
    """Re-rendering an entry with no changes shows unchanged count in stats."""
    _setup_entry_with_llm(
        vault, sha="sha_unch", merchant="Shop", date="2024-01-01", total="$5.00"
    )
    # First render
    runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )
    # Second render — nothing changed
    result = runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "1 unchanged" in result.output


def test_rerender_changed_field_logs_updated(runner, vault):
    """Re-rendering after LLM JSON changes logs 'Updated'."""
    _setup_entry_with_llm(
        vault, sha="sha_upd", merchant="Old Shop", date="2024-01-01", total="$5.00"
    )
    # First render
    runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )
    # Change the LLM JSON
    import json

    llm_json = vault / "papers" / "_assets_" / "sha_upd" / "llm" / "default.json"
    llm_json.write_text(
        json.dumps({"merchant": "New Shop", "date": "2024-01-01", "total": "$5.00"})
    )
    # Re-render with --overwrite to use new LLM values
    result = runner.invoke(
        receipt_pipeline.render_command,
        ["--overwrite", "sha_upd"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert (
        "Renamed: 2024-01-01 - Old Shop - $5.00.md -> 2024-01-01 - New Shop - $5.00.md"
        in result.output
    )
    assert (vault / "papers" / "2024-01-01 - New Shop - $5.00.md").exists()
    assert not (vault / "papers" / "2024-01-01 - Old Shop - $5.00.md").exists()


def test_overwrite_single_sha_deletes_old_md(runner, vault):
    """With sha256, manually edited frontmatter is preserved."""
    _setup_entry_with_llm(
        vault, sha="sha_ow", merchant="LLM Name", date="2024-01-15", total="$42.50"
    )
    # Simulate an existing .md with manually edited merchant
    old_md = vault / "papers" / "2024-01-15 - Edited Name - $42.50.md"
    old_md.write_text(
        '---\nmerchant: "Edited Name"\ndate: "2024-01-15"\ntotal: "$42.50"\n---\n'
        "![[_assets_/sha_ow/src/original.pdf#height]]\n"
    )
    # LLM JSON has different merchant
    import json

    llm_json = vault / "papers" / "_assets_" / "sha_ow" / "llm" / "default.json"
    llm_json.write_text(
        json.dumps({"merchant": "LLM Name", "date": "2024-01-15", "total": "$42.50"})
    )

    result = runner.invoke(
        receipt_pipeline.render_command,
        ["sha_ow"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    # Frontmatter was preserved, title uses edited merchant
    new_md = vault / "papers" / "2024-01-15 - Edited Name - $42.50.md"
    assert new_md.exists()
    content = new_md.read_text()
    assert "merchant: Edited Name" in content


def test_no_llm_json_no_entries(runner, vault):
    """Without llm JSON, no entries are processed."""
    (vault / "papers" / "_assets_" / "sha5").mkdir(parents=True)

    result = runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Created:" not in result.output


def test_render_single_sha256(runner, vault):
    """When sha256 argument is given, only that entry is rendered."""
    _setup_entry_with_llm(
        vault, sha="target", merchant="Target Shop", date="2024-03-01", total="$20.00"
    )
    _setup_entry_with_llm(
        vault, sha="other", merchant="Other Shop", date="2024-04-01", total="$30.00"
    )

    result = runner.invoke(
        receipt_pipeline.render_command,
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
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Created: 2025-06-01 - New Shop - $99.00" in result.output
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
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "2024-07-01 - Photo Shop - $15.00.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "![[_assets_/jpgsha/src/original.jpg]]" in content
    assert "![[_assets_/jpgsha/src/metadata.json]]" in content


def test_preserves_edited_merchant(runner, vault):
    """Manually edited frontmatter merchant is preserved in note and filename."""
    _setup_entry_with_llm(
        vault, sha="sha_pres", merchant="LLM Corp", date="2024-05-01", total="$25.00"
    )
    # First render to create the note
    runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )
    # Manually edit the merchant in frontmatter and rename the file
    old_md = vault / "papers" / "2024-05-01 - LLM Corp - $25.00.md"
    assert old_md.exists()
    content = old_md.read_text().replace("merchant: LLM Corp", "merchant: My Shop")
    new_md = vault / "papers" / "2024-05-01 - My Shop - $25.00.md"
    new_md.write_text(content)
    old_md.unlink()

    # Re-render (frontmatter preserved by default)
    result = runner.invoke(
        receipt_pipeline.render_command,
        ["sha_pres"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    final_md = vault / "papers" / "2024-05-01 - My Shop - $25.00.md"
    assert final_md.exists()
    final_content = final_md.read_text()
    assert "merchant: My Shop" in final_content
    # LLM merchant should NOT appear
    assert "LLM Corp" not in final_content


def test_no_existing_note_uses_llm(runner, vault):
    """With no existing note, LLM values are used as-is."""
    _setup_entry_with_llm(
        vault,
        sha="sha_fresh",
        merchant="Fresh Store",
        date="2024-08-01",
        total="$50.00",
    )

    result = runner.invoke(
        receipt_pipeline.render_command,
        ["sha_fresh"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "2024-08-01 - Fresh Store - $50.00.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "merchant: Fresh Store" in content
    assert "date: 2024-08-01" in content
    assert "total: $50.00" in content


def test_shared_md_preserves_all_embeds(runner, vault):
    """Two shas sharing a title both end up in the same .md after re-render."""
    _setup_entry_with_llm(vault, sha="dup_a")
    _setup_entry_with_llm(vault, sha="dup_b")
    # Pre-create the shared .md with both embeds
    shared_md = vault / "papers" / "2024-01-15 - ACME Store - $42.50.md"
    shared_md.write_text(
        '---\nmerchant: "ACME Store"\ndate: "2024-01-15"\ntotal: "$42.50"\n---\n'
        "![[_assets_/dup_a/src/original.pdf#height]]\n"
        "![[_assets_/dup_a/src/metadata.json]]\n"
        "![[_assets_/dup_b/src/original.pdf#height]]\n"
        "![[_assets_/dup_b/src/metadata.json]]\n"
    )

    result = runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert shared_md.exists()
    content = shared_md.read_text()
    assert "![[_assets_/dup_a/src/original.pdf#height]]" in content
    assert "![[_assets_/dup_b/src/original.pdf#height]]" in content


def test_overwrite_discards_edited_merchant(runner, vault):
    """With --overwrite, manually-edited frontmatter is ignored and LLM values are used."""
    _setup_entry_with_llm(
        vault, sha="sha_disc", merchant="LLM Corp", date="2024-05-01", total="$25.00"
    )
    # First render to create the note
    runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )
    # Manually edit the merchant in frontmatter and rename the file
    old_md = vault / "papers" / "2024-05-01 - LLM Corp - $25.00.md"
    assert old_md.exists()
    content = old_md.read_text().replace("merchant: LLM Corp", "merchant: My Shop")
    new_md = vault / "papers" / "2024-05-01 - My Shop - $25.00.md"
    new_md.write_text(content)
    old_md.unlink()

    # Re-render with --overwrite discards manual edits
    result = runner.invoke(
        receipt_pipeline.render_command,
        ["--overwrite", "sha_disc"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    final_md = vault / "papers" / "2024-05-01 - LLM Corp - $25.00.md"
    assert final_md.exists()
    final_content = final_md.read_text()
    assert "merchant: LLM Corp" in final_content
    # Manual edit should NOT appear
    assert "My Shop" not in final_content


def test_overwrite_fills_empty_fields_from_frontmatter(runner, vault):
    """With --overwrite, empty LLM fields are filled from existing frontmatter."""
    _setup_entry_with_llm(
        vault, sha="sha_fill", merchant="", date="2024-05-01", total="$25.00"
    )
    # Create existing note with a merchant value
    old_md = vault / "papers" / "2024-05-01 - Old Shop - $25.00.md"
    old_md.write_text(
        '---\nmerchant: "Old Shop"\ndate: "2024-05-01"\ntotal: "$25.00"\n---\n'
        "![[_assets_/sha_fill/src/original.pdf#height]]\n"
    )

    result = runner.invoke(
        receipt_pipeline.render_command,
        ["--overwrite", "sha_fill"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    final_md = vault / "papers" / "2024-05-01 - Old Shop - $25.00.md"
    assert final_md.exists()
    assert "merchant: Old Shop" in final_md.read_text()


def test_consumed_at_not_overwritten_by_frontmatter(runner, vault):
    """consumed_at is always from metadata.json, not from existing frontmatter."""
    _setup_entry_with_llm(
        vault,
        sha="sha_ca",
        merchant="Shop",
        date="2024-01-01",
        total="$1.00",
        consumed_at="2024-06-01T12:00:00+00:00",
    )
    old_md = vault / "papers" / "2024-01-01 - Shop - $1.00.md"
    old_md.write_text(
        "---\nmerchant: Shop\ndate: 2024-01-01\ntotal: $1.00\n"
        "consumed_at: 1999-01-01T00:00:00+00:00\n---\n"
        "![[_assets_/sha_ca/src/original.pdf#height]]\n"
    )

    result = runner.invoke(
        receipt_pipeline.render_command,
        ["sha_ca"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    final_md = vault / "papers" / "2024-01-01 - Shop - $1.00.md"
    content = final_md.read_text()
    assert "consumed_at: 2024-06-01T12:00:00+00:00" in content
    assert "1999-01-01" not in content


def test_missing_metadata_json_empty_consumed_at(runner, vault):
    """When metadata.json is missing, consumed_at is an empty string."""
    target_dir = vault / "papers" / "_assets_" / "sha_nometa"
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")
    (llm_dir / "default.json").write_text(
        json.dumps({"merchant": "NoMeta", "date": "2024-01-01", "total": "$1.00"})
    )

    result = runner.invoke(
        receipt_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    md_file = vault / "papers" / "2024-01-01 - NoMeta - $1.00.md"
    assert md_file.exists()
    assert "consumed_at: \n" in md_file.read_text()
