from commands.people import people


def _write_md(vault, rel_path, content):
    md = vault / rel_path
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(content)
    return md


FM_TEMPLATE = (
    "---\ntitle: Doc\ndate: 2024-01-01\ntags:\n  - test\n"
    "people:\n{people_lines}consumed_at: 2024-01-01\n---\n"
    "Body text\n"
)


def _make_fm(*names):
    lines = "".join(f"  - {n}\n" for n in names)
    return FM_TEMPLATE.format(people_lines=lines)


def test_rename_person(runner, vault):
    """Basic rename updates the people list."""
    md = _write_md(vault, "docs/test.md", _make_fm("Alice", "Bob"))

    result = runner.invoke(people, ["rename", "Alice", "Carol"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    content = md.read_text()
    assert "  - Carol\n" in content
    assert "  - Bob\n" in content
    assert "Alice" not in content


def test_rename_deduplicates(runner, vault):
    """Renaming to an existing name removes the duplicate."""
    md = _write_md(vault, "docs/test.md", _make_fm("Alice", "Bob"))

    result = runner.invoke(people, ["rename", "Alice", "Bob"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    content = md.read_text()
    assert content.count("  - Bob\n") == 1
    assert "Alice" not in content


def test_rename_skips_unrelated(runner, vault):
    """Files without the old name are not modified."""
    md = _write_md(vault, "docs/test.md", _make_fm("Bob", "Carol"))

    result = runner.invoke(people, ["rename", "Alice", "Dave"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output
    assert md.read_text() == _make_fm("Bob", "Carol")


def test_rename_no_frontmatter(runner, vault):
    """Files without frontmatter are skipped."""
    md = _write_md(vault, "docs/test.md", "Just plain text\n")

    result = runner.invoke(people, ["rename", "Alice", "Bob"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output
    assert md.read_text() == "Just plain text\n"


def test_rename_skips_assets(runner, vault):
    """Files inside _assets_ directories are skipped."""
    _write_md(vault, "docs/_assets_/sha1/test.md", _make_fm("Alice"))

    result = runner.invoke(people, ["rename", "Alice", "Bob"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output


def test_rename_multiple_files(runner, vault):
    """Rename updates all matching files across subdirectories."""
    md1 = _write_md(vault, "docs/a.md", _make_fm("Alice", "Bob"))
    md2 = _write_md(vault, "stmts/b.md", _make_fm("Alice"))
    md3 = _write_md(vault, "other/c.md", _make_fm("Carol"))

    result = runner.invoke(people, ["rename", "Alice", "Dave"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "2 file(s) updated" in result.output
    assert "Alice" not in md1.read_text()
    assert "  - Dave\n" in md1.read_text()
    assert "Alice" not in md2.read_text()
    assert "  - Dave\n" in md2.read_text()
    # Untouched
    assert md3.read_text() == _make_fm("Carol")


def test_list_people(runner, vault):
    """Lists all unique people names sorted alphabetically."""
    _write_md(vault, "docs/a.md", _make_fm("Alice", "Bob"))
    _write_md(vault, "docs/b.md", _make_fm("Bob", "Carol"))
    _write_md(vault, "docs/c.md", "No frontmatter\n")

    result = runner.invoke(people, ["list"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert result.output.strip() == "Alice\nBob\nCarol"


def test_remove_person(runner, vault):
    """Removing a single name from the people list."""
    md = _write_md(vault, "docs/test.md", _make_fm("Alice", "Bob"))

    result = runner.invoke(people, ["remove", "Alice"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    content = md.read_text()
    assert "  - Bob\n" in content
    assert "Alice" not in content


def test_remove_multiple(runner, vault):
    """Removing multiple names at once."""
    md = _write_md(vault, "docs/test.md", _make_fm("Alice", "Bob", "Carol"))

    result = runner.invoke(
        people, ["remove", "Alice", "Carol"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    content = md.read_text()
    assert "  - Bob\n" in content
    assert "Alice" not in content
    assert "Carol" not in content


def test_remove_all_people(runner, vault):
    """Removing all people leaves an empty people key."""
    md = _write_md(vault, "docs/test.md", _make_fm("Alice"))

    result = runner.invoke(people, ["remove", "Alice"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    content = md.read_text()
    assert "people:\n" in content
    assert "  - " not in content.split("people:\n")[1].split("consumed_at")[0]


def test_remove_skips_unrelated(runner, vault):
    """Files without matching names are not modified."""
    md = _write_md(vault, "docs/test.md", _make_fm("Bob", "Carol"))

    result = runner.invoke(people, ["remove", "Alice"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output
    assert md.read_text() == _make_fm("Bob", "Carol")
