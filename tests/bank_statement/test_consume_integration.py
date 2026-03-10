import hashlib
import json
from unittest.mock import patch

from main import cli

from lib.constants import LLM_MODEL

from tests.conftest import BOTH_KEYS, setup_mock_mistral, setup_mock_openai_bs


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_full_consume_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """End-to-end: invoke through the top-level CLI group."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai_bs(mock_openai_cls)

    pdf = source_dir / "statement.pdf"
    pdf.write_bytes(b"bs integration test")
    expected_hash = hashlib.sha256(b"bs integration test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "bank-statement",
            "--path",
            "stmts",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Ingested" in result.output

    target_dir = vault / "stmts" / "_assets_" / expected_hash
    assert (target_dir / "src" / "original.pdf").exists()
    assert (target_dir / "src" / "metadata.json").exists()
    assert not pdf.exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_default_path_is_bank_statements(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Without --path, files are stored under 'Bank Statements'."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai_bs(mock_openai_cls)

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"default path bs test")
    sha = hashlib.sha256(b"default path bs test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "bank-statement",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert (
        vault / "Bank Statements" / "_assets_" / sha / "src" / "original.pdf"
    ).exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_title_md_created_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Title markdown file is created with BS frontmatter through full CLI."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai_bs(
        mock_openai_cls,
        bank_name="Chase",
        date="2024-01-01",
        end_date="2024-01-31",
        account_name="Checking",
        account_number="1234",
    )

    pdf = source_dir / "statement.pdf"
    pdf.write_bytes(b"title bs cli test")
    sha = hashlib.sha256(b"title bs cli test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "bank-statement",
            "--path",
            "stmts",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    target_dir = vault / "stmts" / "_assets_" / sha
    json_path = target_dir / "llm" / f"{LLM_MODEL}.json"
    assert json_path.exists()
    fields = json.loads(json_path.read_text())
    assert fields["bank_name"] == "Chase"
    assert fields["date"] == "2024-01-01"
    assert fields["end_date"] == "2024-01-31"
    assert fields["account_name"] == "Checking"
    assert fields["account_number"] == "1234"
    # Rendered markdown at vault/stmts/ level
    assert (
        "Created: 2024-01-01 to 2024-01-31 - Chase - Checking - 1234" in result.output
    )
    md_file = vault / "stmts" / "2024-01-01 to 2024-01-31 - Chase - Checking - 1234.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "bank_name: Chase" in content
    assert "date: 2024-01-01" in content
    assert "end_date: 2024-01-31" in content
    assert "account_name: Checking" in content
    assert 'account_number: "1234"' in content
    assert "consumed_at: " in content
    assert f"![[_assets_/{sha}/src/original.pdf#height]]" in content
    assert f"![[_assets_/{sha}/src/metadata.json]]" in content
