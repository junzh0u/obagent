from commands.check import check


def _note(vault, name, sha, notion_id=""):
    """Write a minimal note file under vault/Receipts/."""
    d = vault / "Receipts"
    d.mkdir(parents=True, exist_ok=True)
    nid = f"notion_id: {notion_id}\n" if notion_id else ""
    (d / f"{name}.md").write_text(
        f"---\nmerchant: {name}\n{nid}---\n"
        f"![[_assets_/{sha}/src/original.pdf#height]]\n"
    )


def test_no_collisions(runner, vault):
    _note(vault, "2024-01-01 - Costco - $5.00", "sha1")
    _note(vault, "2024-01-02 - Target - $9.00", "sha2")

    result = runner.invoke(check, [], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "No case collisions." in result.output


def test_collision_reported(runner, vault):
    _note(vault, "2024-01-01 - Costco - $5.00", "sha1")
    _note(vault, "2024-01-01 - costco - $5.00", "sha2")

    result = runner.invoke(check, [], obj={"vault": str(vault)})

    assert result.exit_code == 1
    assert "Collision" in result.output
    assert "would merge into 2024-01-01 - Costco - $5.00.md" in result.output
    # Report-only leaves both files in place.
    assert len(list((vault / "Receipts").glob("*.md"))) == 2


def test_apply_merges_into_linked_note(runner, vault):
    _note(vault, "2024-01-01 - costco - $5.00", "sha_low")
    _note(vault, "2024-01-01 - Costco - $5.00", "sha_cap", notion_id="page-123")

    result = runner.invoke(check, ["--apply"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    mds = list((vault / "Receipts").glob("*.md"))
    # Canonical = the linked note, despite not being lexicographically first.
    assert [m.name for m in mds] == ["2024-01-01 - Costco - $5.00.md"]
    content = mds[0].read_text()
    assert "notion_id: page-123" in content
    assert "![[_assets_/sha_cap/src/original.pdf#height]]" in content
    assert "![[_assets_/sha_low/src/original.pdf#height]]" in content


def test_apply_canonical_is_first_by_name_when_unlinked(runner, vault):
    _note(vault, "2024-01-01 - costco - $5.00", "sha_low")
    _note(vault, "2024-01-01 - Costco - $5.00", "sha_cap")

    result = runner.invoke(check, ["--apply"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    mds = list((vault / "Receipts").glob("*.md"))
    # Uppercase sorts before lowercase, so the capitalized file wins.
    assert [m.name for m in mds] == ["2024-01-01 - Costco - $5.00.md"]


def test_apply_skips_notion_id_conflict(runner, vault):
    _note(vault, "2024-01-01 - Costco - $5.00", "sha_a", notion_id="page-A")
    _note(vault, "2024-01-01 - costco - $5.00", "sha_b", notion_id="page-B")

    result = runner.invoke(check, ["--apply"], obj={"vault": str(vault)})

    assert result.exit_code == 1
    assert "Conflict" in result.output
    # Ambiguous conflict is never merged.
    assert len(list((vault / "Receipts").glob("*.md"))) == 2
