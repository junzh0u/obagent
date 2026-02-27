import json
from unittest.mock import patch

from commands.bank_statement.llm import _postprocess, _prompt, llm
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
        date="2024-01-01",
        end_date="2024-01-31",
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
    assert fields["date"] == "2024-01-01"
    assert fields["end_date"] == "2024-01-31"
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
        date="2025-02-01",
        end_date="2025-02-28",
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
    assert "date" in prompt
    assert "end_date" in prompt
    assert "bank_name" in prompt
    assert "account_name" in prompt
    assert "account_number" in prompt
    assert "JSON" in prompt
    assert '"statements"' in prompt


def test_prompt_function():
    """_prompt builds a prompt with all BS field names."""
    prompt = _prompt("Bank Statements", "OCR text here")
    assert "date" in prompt
    assert "end_date" in prompt
    assert "bank_name" in prompt
    assert "account_name" in prompt
    assert "account_number" in prompt
    assert "OCR text here" in prompt
    assert '"Bank Statements"' in prompt


@patch("commands.llm.OpenAI")
def test_continue_renders_after_llm(mock_openai_cls, runner, vault):
    """--continue triggers render after successful LLM extraction."""
    setup_mock_openai_bs(
        mock_openai_cls,
        bank_name="Chase",
        date="2024-01-01",
        end_date="2024-01-31",
        account_name="Checking",
        account_number="1234",
    )
    target_dir = _setup_entry_with_ocr(vault, sha="sha_cont")
    (target_dir / "src").mkdir(parents=True, exist_ok=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key", "--continue"],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    assert "Extracted:" in result.output
    assert "Title:" in result.output
    md_files = list((vault / "statements").glob("*.md"))
    assert len(md_files) == 1


@patch("commands.llm.OpenAI")
def test_no_continue_skips_render(mock_openai_cls, runner, vault):
    """Without --continue, no markdown note is rendered."""
    setup_mock_openai_bs(mock_openai_cls)
    target_dir = _setup_entry_with_ocr(vault, sha="sha_nocont")
    (target_dir / "src").mkdir(parents=True, exist_ok=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    assert "Extracted:" in result.output
    assert "Title:" not in result.output
    md_files = list((vault / "statements").glob("*.md"))
    assert len(md_files) == 0


@patch("commands.render.render_note", side_effect=RuntimeError("render boom"))
@patch("commands.llm.OpenAI")
def test_continue_render_failure_warns(mock_openai_cls, mock_render, runner, vault):
    """Render failure during --continue emits warning but doesn't abort."""
    setup_mock_openai_bs(mock_openai_cls)
    _setup_entry_with_ocr(vault, sha="sha_fail")

    result = runner.invoke(
        llm,
        ["--openai-api-key", "test-key", "--continue"],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    assert "Warning: note rendering failed: render boom" in result.output


def test_postprocess_strips_bank_name_prefix():
    """account_name with bank_name prefix is cleaned."""
    fields = {"bank_name": "Chase", "account_name": "Chase Total Checking"}
    _postprocess(fields)
    assert fields["account_name"] == "Total Checking"


def test_postprocess_case_insensitive():
    """Bank name prefix is stripped regardless of case."""
    fields = {"bank_name": "Chase", "account_name": "CHASE Sapphire Checking"}
    _postprocess(fields)
    assert fields["account_name"] == "Sapphire Checking"


def test_postprocess_no_prefix():
    """account_name without bank_name prefix is unchanged."""
    fields = {"bank_name": "Chase", "account_name": "Total Checking"}
    _postprocess(fields)
    assert fields["account_name"] == "Total Checking"


def test_postprocess_empty_account_name():
    """Empty account_name is left alone."""
    fields = {"bank_name": "Chase", "account_name": ""}
    _postprocess(fields)
    assert fields["account_name"] == ""


def test_postprocess_missing_bank_name():
    """Missing bank_name skips stripping."""
    fields = {"account_name": "Chase Total Checking"}
    _postprocess(fields)
    assert fields["account_name"] == "Chase Total Checking"


def test_postprocess_strips_colon_suffix():
    """Sub-brand text after colon is stripped from account_name."""
    fields = {"bank_name": "Chase", "account_name": "Freedom: Ultimate Rewards"}
    _postprocess(fields)
    assert fields["account_name"] == "Freedom"


def test_postprocess_no_colon_unchanged():
    """account_name without colon is unchanged."""
    fields = {"bank_name": "Chase", "account_name": "Total Checking"}
    _postprocess(fields)
    assert fields["account_name"] == "Total Checking"


def test_postprocess_strips_trailing_card():
    """Trailing 'Card' is stripped from account_name."""
    fields = {"bank_name": "Citi", "account_name": "It Card"}
    _postprocess(fields)
    assert fields["account_name"] == "It"


def test_postprocess_card_not_stripped_mid_word():
    """'Card' inside a word is not stripped."""
    fields = {"bank_name": "Chase", "account_name": "Cardmember Rewards"}
    _postprocess(fields)
    assert fields["account_name"] == "Cardmember Rewards"


def test_postprocess_truncates_account_number_to_4_digits():
    """Long account numbers are truncated to last 4 digits."""
    fields = {"account_number": "123456789"}
    _postprocess(fields)
    assert fields["account_number"] == "6789"


def test_postprocess_strips_non_digits_from_account_number():
    """Non-digit characters are stripped before truncating."""
    fields = {"account_number": "****1234"}
    _postprocess(fields)
    assert fields["account_number"] == "1234"


def test_postprocess_short_account_number():
    """Account numbers with 4 or fewer digits are kept as-is."""
    fields = {"account_number": "1234"}
    _postprocess(fields)
    assert fields["account_number"] == "1234"
