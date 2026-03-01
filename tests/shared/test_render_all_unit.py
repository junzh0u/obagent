import json

import commands.bank_statement.pipeline  # noqa: F401 — triggers Pipeline registration
import commands.document.pipeline  # noqa: F401
import commands.receipt.pipeline  # noqa: F401

from commands.render import render_all


def _setup_entry(vault, path, sha, llm_data, src_filename="original.pdf"):
    """Create a vault entry with LLM JSON ready for rendering."""
    target_dir = vault / path / "_assets_" / sha
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True, exist_ok=True)
    (target_dir / "src" / src_filename).write_bytes(b"test")
    (target_dir / "src" / "metadata.json").write_text(
        json.dumps(
            {
                "original_filepath": "/test/path",
                "sha256": sha,
                "consumed_at": "2024-06-01T12:00:00+00:00",
            }
        )
    )
    (llm_dir / "default.json").write_text(json.dumps(llm_data))
    return target_dir


def test_renders_all_document_types(runner, vault):
    """Entries across all three document types are rendered in one invocation."""
    _setup_entry(
        vault,
        "Receipts",
        "r1",
        {"merchant": "Coffee Shop", "date": "2024-01-01", "total": "$5.00"},
    )
    _setup_entry(
        vault,
        "Bank Statements",
        "b1",
        {
            "bank_name": "Chase",
            "date": "2024-01-01",
            "end_date": "2024-01-31",
            "account_name": "Checking",
            "account_number": "1234",
        },
    )
    _setup_entry(
        vault,
        "Documents",
        "d1",
        {
            "title": "Tax Return",
            "date": "2024-04-15",
            "tags": "finance,tax",
            "summary": "Annual filing.",
        },
    )

    result = runner.invoke(render_all, [], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert (vault / "Receipts" / "2024-01-01 - Coffee Shop - $5.00.md").exists()
    assert (
        vault
        / "Bank Statements"
        / "2024-01-01 to 2024-01-31 - Chase - Checking - 1234.md"
    ).exists()
    assert (vault / "Documents" / "2024-04-15 - Tax Return.md").exists()


def test_overwrite_flag_forwarded(runner, vault):
    """--overwrite discards manually-edited frontmatter across all types."""
    _setup_entry(
        vault,
        "Receipts",
        "r2",
        {"merchant": "LLM Corp", "date": "2024-05-01", "total": "$25.00"},
    )
    # Create an existing note with manually edited merchant
    papers = vault / "Receipts"
    papers.mkdir(parents=True, exist_ok=True)
    old_md = papers / "2024-05-01 - Edited Name - $25.00.md"
    old_md.write_text(
        "---\nmerchant: Edited Name\ndate: 2024-05-01\ntotal: $25.00\n"
        "consumed_at: 2024-06-01T12:00:00+00:00\n---\n"
        "![[_assets_/r2/src/original.pdf#height]]\n"
        "![[_assets_/r2/src/metadata.json]]\n"
    )

    result = runner.invoke(render_all, ["--overwrite"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    new_md = papers / "2024-05-01 - LLM Corp - $25.00.md"
    assert new_md.exists()
    assert "merchant: LLM Corp" in new_md.read_text()


def test_empty_vault_succeeds(runner, vault):
    """No entries in any type succeeds cleanly without errors."""
    result = runner.invoke(render_all, [], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "Receipt" in result.output
    assert "Bank Statement" in result.output
    assert "Document" in result.output


def test_render_failure_warns_and_continues(runner, vault):
    """A broken entry warns but does not stop processing other entries."""
    # Create a broken receipt entry (LLM JSON with bad data)
    broken_dir = vault / "Receipts" / "_assets_" / "broken"
    (broken_dir / "llm").mkdir(parents=True)
    (broken_dir / "src").mkdir(parents=True)
    (broken_dir / "src" / "original.pdf").write_bytes(b"test")
    (broken_dir / "llm" / "default.json").write_text("not valid json")

    # Create a valid document entry
    _setup_entry(
        vault,
        "Documents",
        "d2",
        {
            "title": "Valid Doc",
            "date": "2024-03-01",
            "tags": "misc",
            "summary": "A valid document.",
        },
    )

    result = runner.invoke(render_all, [], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "Warning" in result.output
    assert (vault / "Documents" / "2024-03-01 - Valid Doc.md").exists()
