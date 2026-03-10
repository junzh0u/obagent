import json
import os
import time
from unittest.mock import patch

import pytest

from commands.receipt.pipeline import _clean_total, receipt_pipeline
from lib.constants import LLM_MODEL

from tests.conftest import setup_mock_openai


def _setup_entry_with_ocr(vault, sha="abc123", ocr_filename="default-ocr.txt"):
    """Create a vault entry with OCR text ready for LLM extraction."""
    target_dir = vault / "papers" / "_assets_" / sha
    ocr_dir = target_dir / "ocr"
    ocr_dir.mkdir(parents=True)
    (target_dir / "original.pdf").write_bytes(b"test")
    (ocr_dir / ocr_filename).write_text(
        "# Page 1\n\nHello world\n\n# Page 2\n\nGoodbye world"
    )
    return target_dir


@patch("commands.llm.OpenAI")
def test_llm_json_created(mock_openai_cls, runner, vault):
    """llm/<LLM_MODEL>.json is created with correct fields."""
    setup_mock_openai(
        mock_openai_cls, merchant="Coffee Shop", date="2024-06-01", total="$5.75"
    )
    _setup_entry_with_ocr(vault, sha="sha1")

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    target_dir = vault / "papers" / "_assets_" / "sha1"
    json_path = target_dir / "llm" / f"{LLM_MODEL}.json"
    assert json_path.exists()
    fields = json.loads(json_path.read_text())
    assert fields["merchant"] == "Coffee Shop"
    assert fields["date"] == "2024-06-01"
    assert fields["total"] == "$5.75"
    assert "Extracted:" in result.output


@patch("commands.llm.OpenAI")
def test_llm_json_includes_prompt(mock_openai_cls, runner, vault):
    """llm/<LLM_MODEL>.json includes the prompt used for extraction."""
    setup_mock_openai(
        mock_openai_cls, merchant="Coffee Shop", date="2024-06-01", total="$5.75"
    )
    _setup_entry_with_ocr(vault, sha="sha_prompt_saved")

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    target_dir = vault / "papers" / "_assets_" / "sha_prompt_saved"
    json_path = target_dir / "llm" / f"{LLM_MODEL}.json"
    data = json.loads(json_path.read_text())
    assert "prompt" in data
    assert "partially read by OCR" in data["prompt"]
    assert "{path}" in data["prompt"]
    assert "{ocr_text}" in data["prompt"]
    assert "# Page 1" not in data["prompt"]


@patch("commands.llm.OpenAI")
def test_llm_uses_openai_gpt5_mini(mock_openai_cls, runner, vault):
    """Field extraction calls OpenAI with correct model and OCR text."""
    mock_openai_client = setup_mock_openai(mock_openai_cls)
    _setup_entry_with_ocr(vault, sha="sha3")

    runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    mock_openai_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_openai_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == LLM_MODEL
    prompt = call_kwargs.kwargs["messages"][0]["content"]
    assert "partially read by OCR" in prompt
    assert '"papers"' in prompt
    assert "merchant" in prompt
    assert "date" in prompt
    assert "total" in prompt
    assert "JSON" in prompt
    assert "# Page 1" in prompt


@patch("commands.llm.OpenAI")
def test_llm_skip_existing_json(mock_openai_cls, runner, vault):
    """LLM extraction is skipped when llm/<LLM_MODEL>.json already exists."""
    setup_mock_openai(mock_openai_cls)
    target_dir = _setup_entry_with_ocr(vault, sha="sha4")
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / f"{LLM_MODEL}.json").write_text('{"merchant": "Old"}')

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "already exists, skipping" in result.output
    mock_openai_cls.return_value.chat.completions.create.assert_not_called()


@patch("commands.llm.OpenAI")
def test_llm_overwrite_reruns(mock_openai_cls, runner, vault):
    """With --overwrite, LLM is re-run even when json exists."""
    setup_mock_openai(
        mock_openai_cls, merchant="New Shop", date="2025-01-01", total="$99.00"
    )
    target_dir = _setup_entry_with_ocr(vault, sha="sha5")
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / f"{LLM_MODEL}.json").write_text('{"merchant": "Old"}')

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key", "--overwrite"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    fields = json.loads((llm_dir / f"{LLM_MODEL}.json").read_text())
    assert fields["merchant"] == "New Shop"
    assert "Extracted:" in result.output


@patch("commands.llm.OpenAI")
def test_llm_custom_model(mock_openai_cls, runner, vault):
    """--llm-model saves json under the custom model name."""
    mock_client = setup_mock_openai(
        mock_openai_cls, merchant="Custom", date="2025-06-01", total="$1.00"
    )
    _setup_entry_with_ocr(vault, sha="sha6")

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key", "--llm-model", "custom-model"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    target_dir = vault / "papers" / "_assets_" / "sha6"
    assert (target_dir / "llm" / "custom-model.json").exists()
    call_kwargs = mock_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "custom-model"


@patch("commands.llm.OpenAI")
def test_llm_single_sha256(mock_openai_cls, runner, vault):
    """When sha256 argument is given, only that entry is processed."""
    setup_mock_openai(mock_openai_cls)
    _setup_entry_with_ocr(vault, sha="target")
    _setup_entry_with_ocr(vault, sha="other")

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key", "target"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert (
        vault / "papers" / "_assets_" / "target" / "llm" / f"{LLM_MODEL}.json"
    ).exists()
    assert not (vault / "papers" / "_assets_" / "other" / "llm").exists()


@patch("commands.llm.OpenAI")
def test_llm_picks_newest_ocr_txt(mock_openai_cls, runner, vault):
    """When multiple OCR txt files exist, the newest by mtime is used."""
    setup_mock_openai(mock_openai_cls)
    target_dir = vault / "papers" / "_assets_" / "sha7"
    ocr_dir = target_dir / "ocr"
    ocr_dir.mkdir(parents=True)
    (target_dir / "original.pdf").write_bytes(b"test")

    old_file = ocr_dir / "old-model.txt"
    old_file.write_text("old ocr content")
    old_mtime = time.time() - 100
    os.utime(old_file, (old_mtime, old_mtime))

    new_file = ocr_dir / "new-model.txt"
    new_file.write_text("new ocr content")

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    call_kwargs = mock_openai_cls.return_value.chat.completions.create.call_args
    prompt = call_kwargs.kwargs["messages"][0]["content"]
    assert "new ocr content" in prompt
    assert "old ocr content" not in prompt


@patch("commands.llm.OpenAI")
def test_migrate_re_extracts_when_fields_missing(mock_openai_cls, runner, vault):
    """--migrate re-runs LLM when existing JSON is missing a field."""
    setup_mock_openai(
        mock_openai_cls, merchant="Coffee Shop", date="2024-06-01", total="$5.75"
    )
    target_dir = _setup_entry_with_ocr(vault, sha="sha_mig")
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    # JSON missing "total"
    (llm_dir / f"{LLM_MODEL}.json").write_text(
        json.dumps({"merchant": "Old", "date": "2024-01-01"})
    )

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key", "--migrate"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Missing fields, re-extracting" in result.output
    fields = json.loads((llm_dir / f"{LLM_MODEL}.json").read_text())
    assert fields["merchant"] == "Coffee Shop"
    assert fields["total"] == "$5.75"


@patch("commands.llm.OpenAI")
def test_migrate_skips_when_all_fields_present(mock_openai_cls, runner, vault):
    """--migrate skips entries that already have all expected fields."""
    setup_mock_openai(mock_openai_cls)
    target_dir = _setup_entry_with_ocr(vault, sha="sha_mig_skip")
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / f"{LLM_MODEL}.json").write_text(
        json.dumps({"merchant": "Shop", "date": "2024-01-01", "total": "$5.00"})
    )

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key", "--migrate"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "already exists, skipping" in result.output
    mock_openai_cls.return_value.chat.completions.create.assert_not_called()


@patch("commands.llm.OpenAI")
def test_migrate_implies_continue(mock_openai_cls, runner, vault):
    """--migrate renders after extraction without needing --continue."""
    setup_mock_openai(
        mock_openai_cls, merchant="Shop", date="2024-06-01", total="$5.00"
    )
    target_dir = _setup_entry_with_ocr(vault, sha="sha_mig_cont")
    (target_dir / "src").mkdir(parents=True, exist_ok=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")
    llm_dir = target_dir / "llm"
    llm_dir.mkdir(parents=True)
    # Missing "total" to trigger re-extraction
    (llm_dir / f"{LLM_MODEL}.json").write_text(
        json.dumps({"merchant": "Old", "date": "2024-01-01"})
    )

    result = runner.invoke(
        receipt_pipeline.llm_command,
        ["--openai-api-key", "test-key", "--migrate"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Extracted:" in result.output
    assert "Created:" in result.output
    md_files = list((vault / "papers").glob("*.md"))
    assert len(md_files) == 1


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$5.00", "$5.00"),
        ("$5.00 USD", "$5.00"),
        ("USD 5.00", "$5.00"),
        ("USD$ 88.41", "$88.41"),
        ("EUR 10.00", "€10.00"),
        ("£29.99", "£29.99"),
        ("GBP 29.99", "£29.99"),
        ("CAD$ 15.00", "$15.00"),
        ("¥1200", "¥1200"),
        ("JPY 1200", "¥1200"),
        ("$42.50 CAD", "$42.50"),
        ("RMB 66.00", "¥66.00"),
        ("¥66.00 RMB", "¥66.00"),
    ],
)
def test_clean_total(raw, expected):
    """_clean_total strips currency codes/names, keeping symbol + number."""
    assert _clean_total(raw) == expected
