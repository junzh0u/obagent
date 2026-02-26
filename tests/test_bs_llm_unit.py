import json
from unittest.mock import patch

from commands.bank_statement.llm import _prompt, llm
from constants import LLM_MODEL

from tests.conftest import setup_mock_openai_bs


def _setup_entry_with_ocr(vault, sha="abc123", ocr_filename="default-ocr.txt"):
    """Create a vault entry with OCR text ready for LLM extraction."""
    target_dir = vault / "statements" / "_assets_" / sha
    ocr_dir = target_dir / "ocr"
    ocr_dir.mkdir(parents=True)
    (target_dir / "original.pdf").write_bytes(b"test")
    (ocr_dir / ocr_filename).write_text(
        "# Page 1\n\nChase Bank Statement\n\n# Page 2\n\nAccount: 1234"
    )
    return target_dir


@patch("commands.llm.OpenAI")
def test_llm_json_created(mock_openai_cls, runner, vault):
    """llm/<LLM_MODEL>.json is created with correct BS fields."""
    setup_mock_openai_bs(
        mock_openai_cls,
        bank_name="Chase",
        date_period="2024-01",
        account_name="Checking",
        account_number="1234",
    )
    _setup_entry_with_ocr(vault, sha="sha1")

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    target_dir = vault / "statements" / "_assets_" / "sha1"
    json_path = target_dir / "llm" / f"{LLM_MODEL}.json"
    assert json_path.exists()
    fields = json.loads(json_path.read_text())
    assert fields["bank_name"] == "Chase"
    assert fields["date_period"] == "2024-01"
    assert fields["account_name"] == "Checking"
    assert fields["account_number"] == "1234"
    assert "Extracted:" in result.output


@patch("commands.llm.OpenAI")
def test_llm_skip_existing_json(mock_openai_cls, runner, vault):
    """LLM extraction is skipped when llm/<LLM_MODEL>.json already exists."""
    setup_mock_openai_bs(mock_openai_cls)
    target_dir = _setup_entry_with_ocr(vault, sha="sha2")
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / f"{LLM_MODEL}.json").write_text('{"bank_name": "Old"}')

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    assert "already exists, skipping" in result.output
    mock_openai_cls.return_value.chat.completions.create.assert_not_called()


@patch("commands.llm.OpenAI")
def test_llm_overwrite_reruns(mock_openai_cls, runner, vault):
    """With --overwrite, LLM is re-run even when json exists."""
    setup_mock_openai_bs(
        mock_openai_cls,
        bank_name="Wells Fargo",
        date_period="2025-02",
        account_name="Savings",
        account_number="5678",
    )
    target_dir = _setup_entry_with_ocr(vault, sha="sha3")
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / f"{LLM_MODEL}.json").write_text('{"bank_name": "Old"}')

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key", "--overwrite"],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    fields = json.loads((llm_dir / f"{LLM_MODEL}.json").read_text())
    assert fields["bank_name"] == "Wells Fargo"
    assert "Extracted:" in result.output


@patch("commands.llm.OpenAI")
def test_llm_single_sha256(mock_openai_cls, runner, vault):
    """When sha256 argument is given, only that entry is processed."""
    setup_mock_openai_bs(mock_openai_cls)
    _setup_entry_with_ocr(vault, sha="target")
    _setup_entry_with_ocr(vault, sha="other")

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key", "target"],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    assert (
        vault / "statements" / "_assets_" / "target" / "llm" / f"{LLM_MODEL}.json"
    ).exists()
    assert not (vault / "statements" / "_assets_" / "other" / "llm").exists()


@patch("commands.llm.OpenAI")
def test_llm_prompt_content(mock_openai_cls, runner, vault):
    """BS prompt includes expected field names."""
    mock_client = setup_mock_openai_bs(mock_openai_cls)
    _setup_entry_with_ocr(vault, sha="sha_prompt")

    runner.invoke(
        llm,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "statements"},
    )

    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args
    prompt = call_kwargs.kwargs["messages"][0]["content"]
    assert "date_period" in prompt
    assert "bank_name" in prompt
    assert "account_name" in prompt
    assert "account_number" in prompt
    assert "JSON" in prompt
    assert '"statements"' in prompt


def test_prompt_function():
    """_prompt builds a prompt with all BS field names."""
    prompt = _prompt("Bank_Statements", "OCR text here")
    assert "date_period" in prompt
    assert "bank_name" in prompt
    assert "account_name" in prompt
    assert "account_number" in prompt
    assert "OCR text here" in prompt
    assert '"Bank_Statements"' in prompt
