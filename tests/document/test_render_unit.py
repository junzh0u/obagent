import json

from commands.document.pipeline import DocumentFields, document_pipeline


def _setup_entry_with_llm(
    vault,
    sha="abc123",
    llm_filename="default.json",
    src_filename="original.pdf",
    consumed_at="2024-06-01T12:00:00+00:00",
    **fields,
):
    """Create a vault entry with LLM JSON ready for rendering."""
    defaults = {
        "title": "Tax Return 2024",
        "date": "2024-04-15",
        "tags": "finance, tax",
        "people": "",
        "summary": "Annual federal tax return filing.",
    }
    defaults.update(fields)
    target_dir = vault / "docs" / "_assets_" / sha
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
    """A <title>.md file is created with document frontmatter and embed link."""
    _setup_entry_with_llm(
        vault,
        sha="sha1",
        title="Tax Return 2024",
        date="2024-04-15",
        tags="finance, tax",
        summary="Annual federal tax return filing.",
    )

    result = runner.invoke(
        document_pipeline.render_command,
        [],
        obj={"vault": str(vault), "path": "docs"},
    )

    assert result.exit_code == 0
    md_file = vault / "docs" / "2024-04-15 - Tax Return 2024.md"
    assert md_file.exists()
    content = md_file.read_text()
    fm = content.split("---")[1]
    assert "title: Tax Return 2024" in fm
    assert "date: 2024-04-15" in fm
    assert "- finance" in fm
    assert "- tax" in fm
    assert "consumed_at: 2024-06-01T12:00:00+00:00" in fm
    assert "summary" not in fm
    assert "> [!summary]" in content
    assert "> Annual federal tax return filing." in content
    assert "![[_assets_/sha1/src/original.pdf#height]]" in content
    assert "![[_assets_/sha1/src/metadata.json]]" in content


def test_make_title_date_and_title():
    """date and title are joined with ' - '."""
    fields = DocumentFields({"title": "Tax Return 2024", "date": "2024-04-15"})
    assert fields.make_title() == "2024-04-15 - Tax Return 2024"


def test_make_title_no_date():
    """When date is empty, only title is used."""
    fields = DocumentFields({"title": "Tax Return 2024", "date": ""})
    assert fields.make_title() == "Tax Return 2024"


def test_make_title_no_title():
    """When title is missing, only date is used."""
    fields = DocumentFields({"date": "2024-04-15"})
    assert fields.make_title() == "2024-04-15"


def test_make_title_strips_unsafe_chars():
    """Unsafe filename and Obsidian-reserved characters are stripped."""
    fields = DocumentFields({"title": 'Report: "Q1/Q2"', "date": "2024-04-15"})
    assert fields.make_title() == "2024-04-15 - Report Q1Q2"
    fields = DocumentFields({"title": "Section #1 [Draft] ^ref", "date": "2024-04-15"})
    assert fields.make_title() == "2024-04-15 - Section 1 Draft ref"


def test_make_title_empty():
    """All missing fields produce empty string."""
    empty = DocumentFields({})
    assert empty.make_title() == ""


def test_frontmatter_excludes_summary():
    """summary is not included in frontmatter."""
    fields = DocumentFields(
        {"title": "Doc", "date": "2024-01-01", "summary": "A short summary."}
    )
    fm = fields.format_frontmatter()
    assert "summary" not in fm


def test_frontmatter_tags_as_yaml_list():
    """Comma-separated tags are rendered as a YAML list."""
    fields = DocumentFields({"title": "Doc", "date": "", "tags": "finance, tax, y2024"})
    fm = fields.format_frontmatter()
    assert "tags:\n  - finance\n  - tax\n  - y2024\n" in fm


def test_frontmatter_empty_tags():
    """Empty tags produce an empty YAML key."""
    fields = DocumentFields({"title": "Doc", "date": "", "tags": ""})
    fm = fields.format_frontmatter()
    assert "tags:\n" in fm
    assert "tags:\n  -" not in fm


def test_frontmatter_people_as_yaml_list():
    """Comma-separated people are rendered as a YAML list."""
    fields = DocumentFields(
        {"title": "Doc", "date": "", "people": "John Doe, Jane Smith"}
    )
    fm = fields.format_frontmatter()
    assert "people:\n  - John Doe\n  - Jane Smith\n" in fm


def test_frontmatter_empty_people():
    """Empty people produce an empty YAML key."""
    fields = DocumentFields({"title": "Doc", "date": "", "people": ""})
    fm = fields.format_frontmatter()
    assert "people:\n" in fm
    assert "people:\n  -" not in fm


def test_format_body_summary_callout():
    """format_body renders summary as an Obsidian callout."""
    fields = DocumentFields({"summary": "A short summary."})
    assert fields.format_body() == "> [!summary]\n> A short summary.\n\n"


def test_format_body_empty_summary():
    """format_body returns empty string when summary is missing."""
    empty = DocumentFields({})
    assert empty.format_body() == ""
    no_summary = DocumentFields({"summary": ""})
    assert no_summary.format_body() == ""
