import json
from unittest.mock import patch

from commands.document.pipeline import DocumentFields, document_pipeline
from constants import LLM_MODEL

from tests.conftest import setup_mock_openai_doc


def _setup_entry_with_ocr(vault, sha="abc123", ocr_filename="default-ocr.txt"):
    """Create a vault entry with OCR text ready for LLM extraction."""
    target_dir = vault / "docs" / "_assets_" / sha
    ocr_dir = target_dir / "ocr"
    ocr_dir.mkdir(parents=True)
    (target_dir / "original.pdf").write_bytes(b"test")
    (ocr_dir / ocr_filename).write_text(
        "# Page 1\n\nTax Return 2024\n\n# Page 2\n\nFiling details"
    )
    return target_dir


@patch("commands.llm.OpenAI")
def test_llm_json_created(mock_openai_cls, runner, vault):
    """llm/<LLM_MODEL>.json is created with correct document fields."""
    setup_mock_openai_doc(
        mock_openai_cls,
        title="Tax Return 2024",
        date="2024-04-15",
        summary="Annual federal tax return filing.",
    )
    _setup_entry_with_ocr(vault, sha="sha1")

    result = runner.invoke(
        document_pipeline.llm_command,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "docs"},
    )

    assert result.exit_code == 0
    target_dir = vault / "docs" / "_assets_" / "sha1"
    json_path = target_dir / "llm" / f"{LLM_MODEL}.json"
    assert json_path.exists()
    fields = json.loads(json_path.read_text())
    assert fields["title"] == "Tax Return 2024"
    assert fields["date"] == "2024-04-15"
    assert fields["summary"] == "Annual federal tax return filing."
    assert "Extracted:" in result.output


@patch("commands.llm.OpenAI")
def test_llm_prompt_content(mock_openai_cls, runner, vault):
    """Document prompt includes expected field names."""
    mock_client = setup_mock_openai_doc(mock_openai_cls)
    _setup_entry_with_ocr(vault, sha="sha_prompt")

    runner.invoke(
        document_pipeline.llm_command,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "docs"},
    )

    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args
    prompt = call_kwargs.kwargs["messages"][0]["content"]
    assert "title" in prompt
    assert "date" in prompt
    assert "tags" in prompt
    assert "people" in prompt
    assert "summary" in prompt
    assert "JSON" in prompt
    assert '"docs"' in prompt


def test_prompt_function():
    """_prompt builds a prompt with all document field names."""
    prompt = document_pipeline.prompt("Documents", "OCR text here")
    assert "title" in prompt
    assert "date" in prompt
    assert "tags" in prompt
    assert "people" in prompt
    assert "summary" in prompt
    assert "OCR text here" in prompt
    assert '"Documents"' in prompt


@patch("commands.llm.OpenAI")
def test_continue_renders_after_llm(mock_openai_cls, runner, vault):
    """--continue triggers render after successful LLM extraction."""
    setup_mock_openai_doc(
        mock_openai_cls,
        title="Tax Return 2024",
        date="2024-04-15",
        summary="Annual federal tax return filing.",
    )
    target_dir = _setup_entry_with_ocr(vault, sha="sha_cont")
    (target_dir / "src").mkdir(parents=True, exist_ok=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")

    result = runner.invoke(
        document_pipeline.llm_command,
        ["--openai-api-key", "test-key", "--continue"],
        obj={"vault": str(vault), "path": "docs"},
    )

    assert result.exit_code == 0
    assert "Extracted:" in result.output
    assert "Created:" in result.output
    md_files = list((vault / "docs").glob("*.md"))
    assert len(md_files) == 1


def test_postprocess_drops_pure_numeric_tags():
    """Pure-numeric tags are dropped (invalid in Obsidian)."""
    fields = DocumentFields({"tags": "finance, 2024, tax"})
    assert fields["tags"] == "finance,tax"


def test_postprocess_strips_invalid_tag_chars():
    """Characters not allowed in Obsidian tags are stripped."""
    fields = DocumentFields({"tags": "hello world, tax@home"})
    assert fields["tags"] == "helloworld,taxhome"


def test_postprocess_valid_tags_unchanged():
    """Valid tags with hyphens, underscores, slashes pass through."""
    fields = DocumentFields({"tags": "year-2024, nested/tag, under_score"})
    assert fields["tags"] == "year-2024,nested/tag,under_score"
