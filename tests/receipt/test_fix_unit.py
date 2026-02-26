from commands.receipt.fix import fix, fix_metadata_embeds
from utils import parse_frontmatter


def _write_note(path_dir, filename, merchant, date, total, extra=""):
    """Create a .md file with frontmatter in path_dir."""
    content = (
        f'---\nmerchant: "{merchant}"\ndate: "{date}"\ntotal: "{total}"\n---\n{extra}'
    )
    md = path_dir / filename
    md.write_text(content)
    return md


def test_rename_when_title_mismatches(runner, vault):
    """File is renamed when its stem doesn't match frontmatter fields."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    _write_note(path_dir, "Old Name.md", "Coffee Shop", "2024-06-01", "$5.75")

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert not (path_dir / "Old Name.md").exists()
    assert (path_dir / "2024-06-01 - Coffee Shop - $5.75.md").exists()
    assert (
        "Renamed: Old Name.md -> 2024-06-01 - Coffee Shop - $5.75.md" in result.output
    )


def test_skip_when_already_correct(runner, vault):
    """No rename or output when filename already matches frontmatter."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    _write_note(
        path_dir,
        "2024-06-01 - Coffee Shop - $5.75.md",
        "Coffee Shop",
        "2024-06-01",
        "$5.75",
    )

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert (path_dir / "2024-06-01 - Coffee Shop - $5.75.md").exists()
    assert "Renamed:" not in result.output
    assert "Fixed 0 name(s), 0 merged, 0 embed(s)" in result.output


def test_skip_missing_frontmatter(runner, vault):
    """Files without frontmatter are skipped with a warning."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    (path_dir / "no-frontmatter.md").write_text("Just some text\n")

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert (path_dir / "no-frontmatter.md").exists()
    assert "Skip (no frontmatter): no-frontmatter.md" in result.output


def test_skip_missing_required_fields(runner, vault):
    """Files with frontmatter but missing merchant/date are skipped."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    (path_dir / "partial.md").write_text('---\ntotal: "$5.00"\n---\n')

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert (path_dir / "partial.md").exists()
    assert "Skip (missing fields): partial.md" in result.output


def test_merge_identical_frontmatter(runner, vault):
    """Two notes with same frontmatter merge; source deleted, target has both embeds."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    _write_note(
        path_dir,
        "Old Name.md",
        "Coffee Shop",
        "2024-06-01",
        "$5.75",
        extra="![[_assets_/sha1/src/original.pdf]]\n",
    )
    _write_note(
        path_dir,
        "2024-06-01 - Coffee Shop - $5.75.md",
        "Coffee Shop",
        "2024-06-01",
        "$5.75",
        extra="![[_assets_/sha2/src/original.pdf]]\n",
    )

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert not (path_dir / "Old Name.md").exists()
    target = path_dir / "2024-06-01 - Coffee Shop - $5.75.md"
    content = target.read_text()
    assert "![[_assets_/sha1/src/original.pdf]]" in content
    assert "![[_assets_/sha2/src/original.pdf]]" in content
    assert "Merged:" in result.output
    assert "1 merged" in result.output


def test_skip_collision_different_frontmatter(runner, vault):
    """Different frontmatter warns, both files remain."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    _write_note(path_dir, "Old Name.md", "Coffee Shop", "2024-06-01", "$5.75")
    # Same merchant/date/total so the target keeps its name, but extra field
    # makes frontmatter dicts differ.
    (path_dir / "2024-06-01 - Coffee Shop - $5.75.md").write_text(
        '---\nmerchant: "Coffee Shop"\ndate: "2024-06-01"'
        '\ntotal: "$5.75"\ncategory: "food"\n---\n'
    )

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert (path_dir / "Old Name.md").exists()
    assert (path_dir / "2024-06-01 - Coffee Shop - $5.75.md").exists()
    assert "Skip (frontmatter differs):" in result.output


def test_merge_no_duplicate_embeds(runner, vault):
    """Shared embeds appear only once after merge."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    _write_note(
        path_dir,
        "Old Name.md",
        "Coffee Shop",
        "2024-06-01",
        "$5.75",
        extra="![[_assets_/sha1/src/original.pdf]]\n",
    )
    _write_note(
        path_dir,
        "2024-06-01 - Coffee Shop - $5.75.md",
        "Coffee Shop",
        "2024-06-01",
        "$5.75",
        extra="![[_assets_/sha1/src/original.pdf]]\n",
    )

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert not (path_dir / "Old Name.md").exists()
    content = (path_dir / "2024-06-01 - Coffee Shop - $5.75.md").read_text()
    assert content.count("![[_assets_/sha1/src/original.pdf]]") == 1
    assert "1 merged" in result.output


def test_merge_runs_fix_metadata_embeds(runner, vault):
    """metadata.json embeds are fixed post-merge."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    _write_note(
        path_dir,
        "Old Name.md",
        "Coffee Shop",
        "2024-06-01",
        "$5.75",
        extra="![[_assets_/sha2/src/original.pdf]]\n",
    )
    _write_note(
        path_dir,
        "2024-06-01 - Coffee Shop - $5.75.md",
        "Coffee Shop",
        "2024-06-01",
        "$5.75",
        extra="![[_assets_/sha1/src/original.pdf]]\n",
    )

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    content = (path_dir / "2024-06-01 - Coffee Shop - $5.75.md").read_text()
    assert "![[_assets_/sha1/src/metadata.json]]" in content
    assert "![[_assets_/sha2/src/metadata.json]]" in content


def test_multiple_renames(runner, vault):
    """Multiple files that need renaming are all fixed."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    _write_note(path_dir, "wrong1.md", "Shop A", "2024-01-01", "$10.00")
    _write_note(path_dir, "wrong2.md", "Shop B", "2024-02-01", "$20.00")

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert (path_dir / "2024-01-01 - Shop A - $10.00.md").exists()
    assert (path_dir / "2024-02-01 - Shop B - $20.00.md").exists()
    assert "Fixed 2 name(s)" in result.output


def test_parse_frontmatter_valid():
    """parse_frontmatter extracts key-value pairs from valid frontmatter."""
    text = '---\nmerchant: "ACME"\ndate: "2024-01-01"\ntotal: "$5.00"\n---\nbody\n'
    fields = parse_frontmatter(text)
    assert fields == {"merchant": "ACME", "date": "2024-01-01", "total": "$5.00"}


def test_parse_frontmatter_no_delimiters():
    """parse_frontmatter returns None when no opening delimiter."""
    assert parse_frontmatter("no frontmatter here") is None


def test_parse_frontmatter_unclosed():
    """parse_frontmatter returns None when closing delimiter is missing."""
    assert parse_frontmatter('---\nmerchant: "ACME"\n') is None


def test_adds_missing_metadata_embed(runner, vault):
    """Fix adds metadata.json embed when source embed exists without one."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    md = path_dir / "2024-06-01 - Coffee Shop - $5.75.md"
    md.write_text(
        '---\nmerchant: "Coffee Shop"\ndate: "2024-06-01"\ntotal: "$5.75"\n---\n'
        "![[_assets_/sha1/src/original.pdf#height]]\n"
    )

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    content = md.read_text()
    assert "![[_assets_/sha1/src/metadata.json]]" in content
    assert "Fixed embeds:" in result.output
    assert "1 embed(s)" in result.output


def test_skips_when_metadata_embed_present(runner, vault):
    """Fix does not duplicate metadata.json embed when already present."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    md = path_dir / "2024-06-01 - Coffee Shop - $5.75.md"
    md.write_text(
        '---\nmerchant: "Coffee Shop"\ndate: "2024-06-01"\ntotal: "$5.75"\n---\n'
        "![[_assets_/sha1/src/original.pdf#height]]\n"
        "![[_assets_/sha1/src/metadata.json]]\n"
    )

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert "Fixed embeds:" not in result.output
    assert "0 embed(s)" in result.output


def test_adds_metadata_for_multiple_shas(runner, vault):
    """Fix adds metadata.json for each sha missing it in a single file."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    md = path_dir / "2024-06-01 - Coffee Shop - $5.75.md"
    md.write_text(
        '---\nmerchant: "Coffee Shop"\ndate: "2024-06-01"\ntotal: "$5.75"\n---\n'
        "![[_assets_/sha1/src/original.pdf#height]]\n"
        "![[_assets_/sha2/src/original.jpg]]\n"
    )

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    content = md.read_text()
    assert "![[_assets_/sha1/src/metadata.json]]" in content
    assert "![[_assets_/sha2/src/metadata.json]]" in content
    assert "1 embed(s)" in result.output


def test_fix_metadata_embeds_inserts_after_source_line(tmp_path):
    """metadata.json embed is inserted on the line after the source embed."""
    md = tmp_path / "test.md"
    md.write_text(
        "![[_assets_/sha1/src/original.pdf#height]]\n"
        "![[_assets_/sha1/src/metadata.json]]\n"
        "![[_assets_/sha2/src/original.jpg]]\n"
    )

    assert fix_metadata_embeds(md)
    lines = md.read_text().splitlines()
    idx = lines.index("![[_assets_/sha2/src/original.jpg]]")
    assert lines[idx + 1] == "![[_assets_/sha2/src/metadata.json]]"


def test_moves_misplaced_metadata_embed(tmp_path):
    """metadata.json embed before the source embed is moved after it."""
    md = tmp_path / "test.md"
    md.write_text(
        "![[_assets_/sha1/src/metadata.json]]\n"
        "![[_assets_/sha1/src/original.pdf#height]]\n"
    )

    assert fix_metadata_embeds(md)
    lines = md.read_text().splitlines()
    assert lines[0] == "![[_assets_/sha1/src/original.pdf#height]]"
    assert lines[1] == "![[_assets_/sha1/src/metadata.json]]"


def test_no_change_when_already_correct(tmp_path):
    """No rewrite when metadata.json is already after source embed."""
    md = tmp_path / "test.md"
    md.write_text(
        "![[_assets_/sha1/src/original.pdf#height]]\n"
        "![[_assets_/sha1/src/metadata.json]]\n"
    )

    assert not fix_metadata_embeds(md)
