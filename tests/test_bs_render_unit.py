import json

from commands.bank_statement.render import make_safe_title, render


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
        "date_period": "2024-01",
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
        date_period="2024-01",
        account_name="Checking",
        account_number="1234",
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    md_file = vault / "statements" / "2024-01 - Chase - Checking - 1234.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "bank_name: Chase" in content
    assert "date_period: 2024-01" in content
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
    md_file = vault / "statements" / "2024-01 - Chase - Checking - 56789.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert 'account_number: "56789"' in content


def test_skip_existing_md(runner, vault):
    """Rendering is skipped when .md already references this sha256."""
    _setup_entry_with_llm(vault, sha="sha2")
    (vault / "statements" / "2024-01 - Chase - Checking - 1234.md").write_text(
        "---\nold: true\n---\n![[_assets_/sha2/src/original.pdf#height]]\n"
    )

    result = runner.invoke(
        render,
        [],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    assert "already exists, skipping" in result.output


def test_append_different_sha(runner, vault):
    """When .md exists but for a different sha256, the new embed is appended."""
    _setup_entry_with_llm(vault, sha="sha3a")
    _setup_entry_with_llm(vault, sha="sha3b")
    md_path = vault / "statements" / "2024-01 - Chase - Checking - 1234.md"

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


def test_overwrite_replaces_md(runner, vault):
    """With --overwrite, all .md files are cleared upfront and re-rendered."""
    _setup_entry_with_llm(
        vault,
        sha="sha4",
        bank_name="BofA",
        date_period="2025-01",
        account_name="Savings",
        account_number="9999",
    )
    stmts_dir = vault / "statements"
    (stmts_dir / "old title.md").write_text("---\nold: true\n---\n")

    result = runner.invoke(
        render,
        ["--overwrite"],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    assert not (stmts_dir / "old title.md").exists()
    assert "Removed 1 notes" in result.output
    new_md = stmts_dir / "2025-01 - BofA - Savings - 9999.md"
    assert new_md.exists()
    content = new_md.read_text()
    assert "bank_name: BofA" in content


def test_make_safe_title_all_fields():
    """All four fields are joined with ' - ' in correct order."""
    assert (
        make_safe_title("Chase", "2024-01", "Checking", "1234")
        == "2024-01 - Chase - Checking - 1234"
    )


def test_make_safe_title_missing_fields():
    """Missing fields are omitted from the title."""
    assert make_safe_title("Chase", "2024-01", None, None) == "2024-01 - Chase"
    assert make_safe_title(None, "2024-01", None, "1234") == "2024-01 - 1234"
    assert make_safe_title("Chase", None, None, None) == "Chase"


def test_make_safe_title_strips_unsafe_chars():
    """Unsafe filename characters are stripped."""
    assert (
        make_safe_title('Chase "Bank"', "2024-01", "Check/Save", "1234")
        == "2024-01 - Chase Bank - CheckSave - 1234"
    )


def test_make_safe_title_empty():
    """All None fields produce empty string."""
    assert make_safe_title(None, None, None, None) == ""
