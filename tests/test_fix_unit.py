from commands.fix import fix, parse_frontmatter


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
    assert "Fixed 0 note(s)" in result.output


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


def test_skip_collision(runner, vault):
    """When target filename already exists, the rename is skipped with a warning."""
    path_dir = vault / "papers"
    path_dir.mkdir()
    _write_note(path_dir, "Old Name.md", "Coffee Shop", "2024-06-01", "$5.75")
    _write_note(
        path_dir,
        "2024-06-01 - Coffee Shop - $5.75.md",
        "Coffee Shop",
        "2024-06-01",
        "$5.75",
        extra="existing content\n",
    )

    result = runner.invoke(fix, [], obj={"vault": str(vault), "path": "papers"})

    assert result.exit_code == 0
    assert (path_dir / "Old Name.md").exists()
    assert "Skip (target exists):" in result.output


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
    assert "Fixed 2 note(s)" in result.output


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
