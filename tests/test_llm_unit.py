from unittest.mock import patch

from commands.llm import llm

from tests.conftest import setup_mock_openai


def _setup_entry_with_ocr(vault, sha="abc123"):
    """Create a vault entry with OCR text ready for LLM extraction."""
    target_dir = vault / "papers" / sha
    ocr_dir = target_dir / "ocr"
    ocr_dir.mkdir(parents=True)
    (target_dir / "original.pdf").write_bytes(b"test")
    (ocr_dir / "mistral-ocr-latest.txt").write_text(
        "# Page 1\n\nHello world\n\n# Page 2\n\nGoodbye world"
    )
    return target_dir


@patch("commands.llm.OpenAI")
def test_title_md_created(mock_openai_cls, runner, vault):
    """A <title>.md file is created with frontmatter and Obsidian embed link."""
    setup_mock_openai(
        mock_openai_cls, merchant="Coffee Shop", date="2024-06-01", total="$5.75"
    )
    _setup_entry_with_ocr(vault, sha="sha1")

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    target_dir = vault / "papers" / "sha1"
    md_file = target_dir / "2024-06-01 - Coffee Shop - $5.75.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert 'merchant: "Coffee Shop"' in content
    assert 'date: "2024-06-01"' in content
    assert 'total: "$5.75"' in content
    assert "![[original.pdf]]" in content
    assert "Title: 2024-06-01 - Coffee Shop - $5.75" in result.output


@patch("commands.llm.OpenAI")
def test_title_sanitizes_unsafe_characters(mock_openai_cls, runner, vault):
    """Unsafe filename characters are stripped from the title."""
    setup_mock_openai(
        mock_openai_cls, merchant='Shop "A"/B', date="2024-01-15", total="$10.00"
    )
    _setup_entry_with_ocr(vault, sha="sha2")

    runner.invoke(
        llm,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    target_dir = vault / "papers" / "sha2"
    md_file = target_dir / "2024-01-15 - Shop AB - $10.00.md"
    assert md_file.exists()
    assert "![[original.pdf]]" in md_file.read_text()


@patch("commands.llm.OpenAI")
def test_title_uses_openai_gpt5_mini(mock_openai_cls, runner, vault):
    """Metadata extraction calls OpenAI gpt-5-mini with OCR text."""
    mock_openai_client = setup_mock_openai(mock_openai_cls)
    _setup_entry_with_ocr(vault, sha="sha3")

    runner.invoke(
        llm,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    mock_openai_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_openai_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "gpt-5-mini"
    prompt = call_kwargs.kwargs["messages"][0]["content"]
    assert "partially read by OCR" in prompt
    assert '"papers"' in prompt
    assert "merchant" in prompt
    assert "date" in prompt
    assert "total" in prompt
    assert "JSON" in prompt
    assert "# Page 1" in prompt


@patch("commands.llm.OpenAI")
def test_llm_skip_existing_md(mock_openai_cls, runner, vault):
    """LLM extraction is skipped when .md file already exists."""
    setup_mock_openai(mock_openai_cls)
    target_dir = _setup_entry_with_ocr(vault, sha="sha4")
    (target_dir / "existing title.md").write_text("---\nold: true\n---\n")

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "already exists, skipping" in result.output
    mock_openai_cls.return_value.chat.completions.create.assert_not_called()


@patch("commands.llm.OpenAI")
def test_llm_overwrite_replaces_md(mock_openai_cls, runner, vault):
    """With --overwrite, old .md files are deleted and new one is created."""
    setup_mock_openai(
        mock_openai_cls, merchant="New Shop", date="2025-01-01", total="$99.00"
    )
    target_dir = _setup_entry_with_ocr(vault, sha="sha5")
    (target_dir / "old title.md").write_text("---\nold: true\n---\n")

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key", "--overwrite"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert not (target_dir / "old title.md").exists()
    new_md = target_dir / "2025-01-01 - New Shop - $99.00.md"
    assert new_md.exists()
    content = new_md.read_text()
    assert 'merchant: "New Shop"' in content
