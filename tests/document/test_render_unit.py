import json

from commands.document.pipeline import DocumentFields, document_pipeline


def _setup_entry_with_llm(
    vault,
    sha="abc123",
    llm_filename="default.json",
    src_filename="original.pdf",
    **fields,
):
    """Create a vault entry with LLM JSON ready for rendering."""
    defaults = {
        "title": "Tax Return 2024",
        "date": "2024-04-15",
        "summary": "Annual federal tax return filing.",
    }
    defaults.update(fields)
    target_dir = vault / "docs" / "_assets_" / sha
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / src_filename).write_bytes(b"test")
    (llm_dir / llm_filename).write_text(json.dumps(defaults))
    return target_dir


def test_md_created_with_frontmatter(runner, vault):
    """A <title>.md file is created with document frontmatter and embed link."""
    _setup_entry_with_llm(
        vault,
        sha="sha1",
        title="Tax Return 2024",
        date="2024-04-15",
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
    assert "title: Tax Return 2024" in content
    assert "date: 2024-04-15" in content
    assert "summary" not in content.split("---")[1]  # not in frontmatter
    assert "> [!summary]" in content
    assert "> Annual federal tax return filing." in content
    assert "![[_assets_/sha1/src/original.pdf#height]]" in content
    assert "![[_assets_/sha1/src/metadata.json]]" in content


def test_make_title_date_and_title():
    """date and title are joined with ' - '."""
    fields: DocumentFields = {"title": "Tax Return 2024", "date": "2024-04-15"}
    assert document_pipeline.make_title(fields) == "2024-04-15 - Tax Return 2024"


def test_make_title_no_date():
    """When date is empty, only title is used."""
    fields: DocumentFields = {"title": "Tax Return 2024", "date": ""}
    assert document_pipeline.make_title(fields) == "Tax Return 2024"


def test_make_title_no_title():
    """When title is missing, only date is used."""
    fields: DocumentFields = {"date": "2024-04-15"}
    assert document_pipeline.make_title(fields) == "2024-04-15"


def test_make_title_strips_unsafe_chars():
    """Unsafe filename and Obsidian-reserved characters are stripped."""
    fields: DocumentFields = {"title": 'Report: "Q1/Q2"', "date": "2024-04-15"}
    assert document_pipeline.make_title(fields) == "2024-04-15 - Report Q1Q2"
    fields: DocumentFields = {"title": "Section #1 [Draft] ^ref", "date": "2024-04-15"}
    assert document_pipeline.make_title(fields) == "2024-04-15 - Section 1 Draft ref"


def test_make_title_empty():
    """All missing fields produce empty string."""
    empty: DocumentFields = {}
    assert document_pipeline.make_title(empty) == ""


def test_frontmatter_excludes_summary():
    """summary is not included in frontmatter."""
    fields: DocumentFields = {
        "title": "Doc",
        "date": "2024-01-01",
        "summary": "A short summary.",
    }
    fm = document_pipeline.format_frontmatter(fields)
    assert "summary" not in fm


def test_format_body_summary_callout():
    """format_body renders summary as an Obsidian callout."""
    fields: DocumentFields = {"summary": "A short summary."}
    assert (
        document_pipeline.format_body(fields) == "> [!summary]\n> A short summary.\n\n"
    )


def test_format_body_empty_summary():
    """format_body returns empty string when summary is missing."""
    empty: DocumentFields = {}
    assert document_pipeline.format_body(empty) == ""
    no_summary: DocumentFields = {"summary": ""}
    assert document_pipeline.format_body(no_summary) == ""
