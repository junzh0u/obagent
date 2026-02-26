import json

from commands.bank_statement.render import make_title, render


def _setup_entry_with_llm(
    vault,
    sha="abc123",
    llm_filename="default.json",
    src_filename="original.pdf",
    **fields,
):
    """Create a vault entry with LLM JSON ready for rendering."""
    defaults = {
        "bank_name": "Chase",
        "date": "2024-01-01",
        "end_date": "2024-01-31",
        "account_name": "Checking",
        "account_number": "1234",
    }
    defaults.update(fields)
    target_dir = vault / "statements" / "_assets_" / sha
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / src_filename).write_bytes(b"test")
    (llm_dir / llm_filename).write_text(json.dumps(defaults))
    return target_dir


def test_md_created_with_frontmatter(runner, vault):
    """A <title>.md file is created with BS frontmatter and embed link."""
    _setup_entry_with_llm(
        vault,
        sha="sha1",
        bank_name="Chase",
        date="2024-01-01",
        end_date="2024-01-31",
        account_name="Checking",
        account_number="1234",
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    md_file = (
        vault / "statements" / "2024-01-01 to 2024-01-31 - Chase - Checking - 1234.md"
    )
    assert md_file.exists()
    content = md_file.read_text()
    assert "bank_name: Chase" in content
    assert "date: 2024-01-01" in content
    assert "end_date: 2024-01-31" in content
    assert "account_name: Checking" in content
    assert 'account_number: "1234"' in content
    assert "![[_assets_/sha1/src/original.pdf#height]]" in content
    assert "![[_assets_/sha1/src/metadata.json]]" in content


def test_account_number_quoted_in_frontmatter(runner, vault):
    """account_number is always quoted in frontmatter."""
    _setup_entry_with_llm(vault, sha="sha_q", account_number="56789")

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    md_file = (
        vault / "statements" / "2024-01-01 to 2024-01-31 - Chase - Checking - 56789.md"
    )
    assert md_file.exists()
    content = md_file.read_text()
    assert 'account_number: "56789"' in content


def test_append_different_sha(runner, vault):
    """When .md exists but for a different sha256, the new embed is appended."""
    _setup_entry_with_llm(vault, sha="sha3a")
    _setup_entry_with_llm(vault, sha="sha3b")
    md_path = (
        vault / "statements" / "2024-01-01 to 2024-01-31 - Chase - Checking - 1234.md"
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    content = md_path.read_text()
    assert "![[_assets_/sha3a/src/original.pdf#height]]" in content
    assert "![[_assets_/sha3b/src/original.pdf#height]]" in content
    assert "Appended to:" in result.output


def test_render_replaces_old_notes(runner, vault):
    """All .md files are cleared upfront and re-rendered."""
    _setup_entry_with_llm(
        vault,
        sha="sha4",
        bank_name="BofA",
        date="2025-01-01",
        end_date="2025-01-31",
        account_name="Savings",
        account_number="9999",
    )
    stmts_dir = vault / "statements"
    (stmts_dir / "old title.md").write_text("---\nold: true\n---\n")

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    assert not (stmts_dir / "old title.md").exists()
    assert "Removed 1 notes" in result.output
    new_md = stmts_dir / "2025-01-01 to 2025-01-31 - BofA - Savings - 9999.md"
    assert new_md.exists()
    content = new_md.read_text()
    assert "bank_name: BofA" in content


def test_make_title_all_fields():
    """All fields are joined with ' - ' in correct order."""
    fields = {
        "bank_name": "Chase",
        "date": "2024-01-01",
        "end_date": "2024-01-31",
        "account_name": "Checking",
        "account_number": "1234",
    }
    assert make_title(fields) == "2024-01-01 to 2024-01-31 - Chase - Checking - 1234"


def test_make_title_no_end_date():
    """When end_date is empty, only date is used."""
    fields = {
        "bank_name": "Chase",
        "date": "2024-01-01",
        "end_date": "",
        "account_name": "Checking",
        "account_number": "1234",
    }
    assert make_title(fields) == "2024-01-01 - Chase - Checking - 1234"


def test_make_title_missing_fields():
    """Missing fields are omitted from the title."""
    assert (
        make_title({"bank_name": "Chase", "date": "2024-01-01"}) == "2024-01-01 - Chase"
    )
    assert (
        make_title({"date": "2024-01-01", "account_number": "1234"})
        == "2024-01-01 - 1234"
    )
    assert make_title({"bank_name": "Chase"}) == "Chase"


def test_make_title_strips_unsafe_chars():
    """Unsafe filename characters are stripped."""
    fields = {
        "bank_name": 'Chase "Bank"',
        "date": "2024-01-01",
        "end_date": "",
        "account_name": "Check/Save",
        "account_number": "1234",
    }
    assert make_title(fields) == "2024-01-01 - Chase Bank - CheckSave - 1234"


def test_make_title_empty():
    """All missing fields produce empty string."""
    assert make_title({}) == ""
