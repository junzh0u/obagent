import json

from commands.receipt.pipeline import receipt_pipeline

set_cmd = receipt_pipeline.set_command


def _setup_entry(vault, sha="deadbeef", **fields):
    """Create a vault entry with LLM JSON and rendered .md."""
    defaults = {"merchant": "ACME Store", "date": "2024-01-15", "total": "$42.50"}
    defaults.update(fields)
    target_dir = vault / "Receipts" / "_assets_" / sha
    for sub in ("src", "ocr", "llm"):
        (target_dir / sub).mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")
    (target_dir / "llm" / "default.json").write_text(json.dumps(defaults))

    title = f"{defaults['date']} - {defaults['merchant']} - {defaults['total']}"
    md_path = vault / "Receipts" / f"{title}.md"
    frontmatter = (
        f"---\nmerchant: {defaults['merchant']}\n"
        f"date: {defaults['date']}\ntotal: {defaults['total']}\n---\n"
    )
    md_path.write_text(
        frontmatter
        + f"![[_assets_/{sha}/src/original.pdf#height]]\n"
        + f"![[_assets_/{sha}/src/metadata.json]]\n"
    )
    return target_dir, md_path


def test_set_by_sha_updates_json_and_renames_note(runner, vault):
    """The value lands in the LLM JSON (the render source) and the note follows."""
    target_dir, md_path = _setup_entry(vault, total="$29,437")

    result = runner.invoke(
        set_cmd,
        ["deadbeef", "total", "JPY 29,437"],
        obj={"vault": str(vault), "path": "Receipts"},
    )

    assert result.exit_code == 0
    data = json.loads((target_dir / "llm" / "default.json").read_text())
    assert data["total"] == "JPY 29,437"
    assert not md_path.exists()
    new_path = vault / "Receipts" / "2024-01-15 - ACME Store - JPY 29,437.md"
    assert new_path.exists()
    assert "total: JPY 29,437" in new_path.read_text()


def test_set_by_note_filename(runner, vault):
    """A bare note filename resolves inside the type dir."""
    target_dir, md_path = _setup_entry(vault)

    result = runner.invoke(
        set_cmd,
        [md_path.name, "merchant", "ACME Corp"],
        obj={"vault": str(vault), "path": "Receipts"},
    )

    assert result.exit_code == 0
    data = json.loads((target_dir / "llm" / "default.json").read_text())
    assert data["merchant"] == "ACME Corp"
    assert (vault / "Receipts" / "2024-01-15 - ACME Corp - $42.50.md").exists()


def test_set_beats_preserved_frontmatter(runner, vault):
    """The set field overrides the note's frontmatter (which render preserves),
    while other frontmatter-corrected fields survive."""
    target_dir, md_path = _setup_entry(vault)
    # Frontmatter was manually corrected earlier: merchant differs from LLM JSON.
    md_path.write_text(md_path.read_text().replace("ACME Store", "ACME Corp"))
    md_path.rename(vault / "Receipts" / "2024-01-15 - ACME Corp - $42.50.md")

    result = runner.invoke(
        set_cmd,
        ["deadbeef", "total", "$99.99"],
        obj={"vault": str(vault), "path": "Receipts"},
    )

    assert result.exit_code == 0
    new_path = vault / "Receipts" / "2024-01-15 - ACME Corp - $99.99.md"
    assert new_path.exists()  # merchant correction kept, total overwritten


def test_set_unknown_field_errors(runner, vault):
    _setup_entry(vault)

    result = runner.invoke(
        set_cmd,
        ["deadbeef", "amount", "$1.00"],
        obj={"vault": str(vault), "path": "Receipts"},
    )

    assert result.exit_code != 0
    assert "Unknown receipt field" in result.output
    assert "total" in result.output  # the valid keys are listed


def test_set_multi_embed_note_errors(runner, vault):
    """A note with several sources is ambiguous — the sha must be given."""
    _setup_entry(vault, sha="sha_a")
    _setup_entry(vault, sha="sha_b")
    md_path = vault / "Receipts" / "2024-01-15 - ACME Store - $42.50.md"
    md_path.write_text(
        "---\nmerchant: ACME Store\ndate: 2024-01-15\ntotal: $42.50\n---\n"
        "![[_assets_/sha_a/src/original.pdf#height]]\n"
        "![[_assets_/sha_b/src/original.pdf#height]]\n"
    )

    result = runner.invoke(
        set_cmd,
        [md_path.name, "total", "$1.00"],
        obj={"vault": str(vault), "path": "Receipts"},
    )

    assert result.exit_code != 0
    assert "embeds 2 sources" in result.output


def test_set_missing_llm_result_errors(runner, vault):
    target_dir = vault / "Receipts" / "_assets_" / "nollm"
    (target_dir / "src").mkdir(parents=True)

    result = runner.invoke(
        set_cmd,
        ["nollm", "total", "$1.00"],
        obj={"vault": str(vault), "path": "Receipts"},
    )

    assert result.exit_code != 0
    assert "No LLM result" in result.output
