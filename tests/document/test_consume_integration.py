import hashlib
import json
from unittest.mock import patch

from main import cli

from constants import LLM_MODEL

from tests.conftest import BOTH_KEYS, setup_mock_mistral, setup_mock_openai_doc


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_full_consume_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """End-to-end: invoke through the top-level CLI group."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai_doc(mock_openai_cls)

    pdf = source_dir / "document.pdf"
    pdf.write_bytes(b"doc integration test")
    expected_hash = hashlib.sha256(b"doc integration test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "document",
            "--path",
            "docs",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Ingested" in result.output

    target_dir = vault / "docs" / "_assets_" / expected_hash
    assert (target_dir / "src" / "original.pdf").exists()
    assert (target_dir / "src" / "metadata.json").exists()
    assert not pdf.exists()

    json_path = target_dir / "llm" / f"{LLM_MODEL}.json"
    assert json_path.exists()
    fields = json.loads(json_path.read_text())
    assert fields["title"] == "Tax Return 2024"
    assert fields["date"] == "2024-04-15"
    assert fields["summary"] == "Annual federal tax return filing."

    assert "Title: 2024-04-15 - Tax Return 2024" in result.output
    md_file = vault / "docs" / "2024-04-15 - Tax Return 2024.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "title: Tax Return 2024" in content
    assert "date: 2024-04-15" in content
    assert "consumed_at: " in content
    assert "> [!summary]" in content
    assert "> Annual federal tax return filing." in content
    assert f"![[_assets_/{expected_hash}/src/original.pdf#height]]" in content
    assert f"![[_assets_/{expected_hash}/src/metadata.json]]" in content


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_default_path_is_documents(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Without --path, files are stored under 'Documents'."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai_doc(mock_openai_cls)

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"default path doc test")
    sha = hashlib.sha256(b"default path doc test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "document",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert (vault / "Documents" / "_assets_" / sha / "src" / "original.pdf").exists()
