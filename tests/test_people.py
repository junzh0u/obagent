import json

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

    result = runner.invoke(
        people, ["rename", "Alice", "Carol"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    content = md.read_text()
    assert "  - Carol\n" in content
    assert "  - Bob\n" in content
    assert "Alice" not in content


def test_rename_deduplicates(runner, vault):
    """Renaming to an existing name removes the duplicate."""
    md = _write_md(vault, "docs/test.md", _make_fm("Alice", "Bob"))

    result = runner.invoke(
        people, ["rename", "Alice", "Bob"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    content = md.read_text()
    assert content.count("  - Bob\n") == 1
    assert "Alice" not in content


def test_rename_skips_unrelated(runner, vault):
    """Files without the old name are not modified."""
    md = _write_md(vault, "docs/test.md", _make_fm("Bob", "Carol"))

    result = runner.invoke(
        people, ["rename", "Alice", "Dave"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output
    assert md.read_text() == _make_fm("Bob", "Carol")


def test_rename_no_frontmatter(runner, vault):
    """Files without frontmatter are skipped."""
    md = _write_md(vault, "docs/test.md", "Just plain text\n")

    result = runner.invoke(
        people, ["rename", "Alice", "Bob"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output
    assert md.read_text() == "Just plain text\n"


def test_rename_skips_assets(runner, vault):
    """Files inside _assets_ directories are skipped."""
    _write_md(vault, "docs/_assets_/sha1/test.md", _make_fm("Alice"))

    result = runner.invoke(
        people, ["rename", "Alice", "Bob"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output


def test_rename_multiple_files(runner, vault):
    """Rename updates all matching files across subdirectories."""
    md1 = _write_md(vault, "docs/a.md", _make_fm("Alice", "Bob"))
    md2 = _write_md(vault, "stmts/b.md", _make_fm("Alice"))
    md3 = _write_md(vault, "other/c.md", _make_fm("Carol"))

    result = runner.invoke(
        people, ["rename", "Alice", "Dave"], obj={"vault": str(vault)}
    )

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


def test_remap_from_explicit_path(runner, vault, tmp_path):
    """Remap with an explicit JSON mapping file."""
    md = _write_md(vault, "docs/test.md", _make_fm("Zhou Jun", "Alice"))
    mapping_file = tmp_path / "remap.json"
    mapping_file.write_text(json.dumps({"Zhou Jun": "Jun Zhou"}))

    result = runner.invoke(
        people, ["remap", str(mapping_file)], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    content = md.read_text()
    assert "  - Jun Zhou\n" in content
    assert "  - Alice\n" in content
    assert "Zhou Jun" not in content


def test_remap_from_default_path(runner, vault):
    """Remap reads from vault/.obagent/people-aliases.json by default."""
    md = _write_md(vault, "docs/test.md", _make_fm("Zhou Jun", "Zhu Xiang"))
    mapping_dir = vault / ".obagent"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / "people-aliases.json").write_text(
        json.dumps({"Zhou Jun": "Jun Zhou", "Zhu Xiang": "Xiang Zhu"})
    )

    result = runner.invoke(people, ["remap"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    content = md.read_text()
    assert "  - Jun Zhou\n" in content
    assert "  - Xiang Zhu\n" in content


def test_remap_missing_file(runner, vault):
    """Error when no mapping file exists."""
    result = runner.invoke(people, ["remap"], obj={"vault": str(vault)})

    assert result.exit_code != 0
    assert "Mapping file not found" in result.output


def test_remap_no_matches(runner, vault, tmp_path):
    """Mapping names not present in vault results in 0 updates."""
    _write_md(vault, "docs/test.md", _make_fm("Alice", "Bob"))
    mapping_file = tmp_path / "remap.json"
    mapping_file.write_text(json.dumps({"Unknown": "Someone"}))

    result = runner.invoke(
        people, ["remap", str(mapping_file)], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output


def test_remap_empty_value_removes(runner, vault, tmp_path):
    """Mapping to empty string removes the person."""
    md = _write_md(vault, "docs/test.md", _make_fm("Alice", "Bob"))
    mapping_file = tmp_path / "remap.json"
    mapping_file.write_text(json.dumps({"Alice": ""}))

    result = runner.invoke(
        people, ["remap", str(mapping_file)], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    content = md.read_text()
    assert "  - Bob\n" in content
    assert "Alice" not in content


def test_rename_saves_to_aliases(runner, vault):
    """Accepting the save prompt writes sorted JSON to the aliases file."""
    _write_md(vault, "docs/test.md", _make_fm("Bob", "Alice"))

    result = runner.invoke(
        people,
        ["rename", "Alice", "Carol"],
        obj={"vault": str(vault)},
        input="y\n",
    )

    assert result.exit_code == 0
    aliases = vault / ".obagent" / "people-aliases.json"
    assert aliases.exists()
    data = json.loads(aliases.read_text())
    assert data == {"Alice": "Carol"}


def test_rename_declines_save(runner, vault):
    """Declining the save prompt does not create the aliases file."""
    _write_md(vault, "docs/test.md", _make_fm("Alice"))

    result = runner.invoke(
        people,
        ["rename", "Alice", "Bob"],
        obj={"vault": str(vault)},
        input="n\n",
    )

    assert result.exit_code == 0
    assert not (vault / ".obagent" / "people-aliases.json").exists()


def test_rename_no_save_when_zero_updates(runner, vault):
    """No save prompt when nothing was renamed."""
    _write_md(vault, "docs/test.md", _make_fm("Bob"))

    result = runner.invoke(
        people,
        ["rename", "Alice", "Carol"],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert "Save to" not in result.output


def test_remove_saves_to_aliases(runner, vault):
    """Remove saves empty-string mapping when user confirms."""
    _write_md(vault, "docs/test.md", _make_fm("Alice", "Bob"))

    result = runner.invoke(
        people,
        ["remove", "Alice"],
        obj={"vault": str(vault)},
        input="y\n",
    )

    assert result.exit_code == 0
    data = json.loads((vault / ".obagent" / "people-aliases.json").read_text())
    assert data == {"Alice": ""}


def test_save_merges_with_existing(runner, vault):
    """Saving merges with existing aliases and keeps keys sorted."""
    aliases_dir = vault / ".obagent"
    aliases_dir.mkdir(parents=True)
    (aliases_dir / "people-aliases.json").write_text(json.dumps({"Zara": "Zara Z"}))
    _write_md(vault, "docs/test.md", _make_fm("Alice", "Bob"))

    result = runner.invoke(
        people,
        ["rename", "Alice", "Carol"],
        obj={"vault": str(vault)},
        input="y\n",
    )

    assert result.exit_code == 0
    data = json.loads((vault / ".obagent" / "people-aliases.json").read_text())
    assert data == {"Alice": "Carol", "Zara": "Zara Z"}
    assert list(data.keys()) == ["Alice", "Zara"]  # sorted
