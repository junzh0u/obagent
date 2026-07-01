"""Smart inbox: `obagent consume` classifies loose files in the inbox root."""

import hashlib
from unittest.mock import patch

import commands.bank_statement.pipeline  # noqa: F401 — register pipelines
import commands.document.pipeline  # noqa: F401
import commands.receipt.pipeline  # noqa: F401

from commands.consume import consume_all
from commands.receipt.pipeline import receipt_pipeline
from lib.constants import ASSETS_DIR

from tests.conftest import BOTH_KEYS


def _setup_ctx_managers(mock_mistral, mock_openai):
    for mock in (mock_mistral, mock_openai):
        mock.return_value.__enter__ = lambda self: self
        mock.return_value.__exit__ = lambda self, *args: False


def _invoke(inbox, vault, runner, extra=()):
    return runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox), *extra],
        obj={"vault": str(vault)},
    )


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.classify_document")
@patch("commands.consume.run_ocr")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_classifies_loose_root_file(
    mock_mistral,
    mock_openai,
    mock_ocr,
    mock_classify,
    mock_llm,
    mock_render,
    runner,
    vault,
    tmp_path,
    monkeypatch,
):
    """A loose root file is OCR'd, classified, relocated under the type, root removed."""
    monkeypatch.delenv("OBAGENT_CONSUME_PREHOOK", raising=False)
    _setup_ctx_managers(mock_mistral, mock_openai)
    mock_classify.return_value = receipt_pipeline
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    pdf = inbox / "loose.pdf"
    pdf.write_bytes(b"loose content")
    sha = hashlib.sha256(b"loose content").hexdigest()

    result = _invoke(inbox, vault, runner)

    assert result.exit_code == 0, result.output
    # relocated under the classified type, with its OCR carried along
    assert (vault / "Receipts" / ASSETS_DIR / sha / "src" / "original.pdf").exists()
    assert not pdf.exists()  # root original consumed
    assert not (vault / ".obagent" / "staging").exists()  # staging cleaned
    mock_ocr.assert_called_once()
    mock_classify.assert_called_once()
    mock_llm.assert_called_once()
    mock_render.assert_called_once()
    assert "Classified as Receipts" in result.output


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.classify_document")
@patch("commands.consume.run_ocr")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_no_classify_flag_leaves_root_files(
    mock_mistral,
    mock_openai,
    mock_ocr,
    mock_classify,
    mock_llm,
    mock_render,
    runner,
    vault,
    tmp_path,
    monkeypatch,
):
    """--no-classify ignores loose root files entirely."""
    monkeypatch.delenv("OBAGENT_CONSUME_PREHOOK", raising=False)
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    pdf = inbox / "loose.pdf"
    pdf.write_bytes(b"loose content")

    result = _invoke(inbox, vault, runner, extra=["--no-classify"])

    assert result.exit_code == 0, result.output
    assert pdf.exists()  # untouched
    mock_ocr.assert_not_called()
    mock_classify.assert_not_called()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.classify_document")
@patch("commands.consume.run_ocr")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_already_consumed_root_file_is_skipped(
    mock_mistral,
    mock_openai,
    mock_ocr,
    mock_classify,
    mock_llm,
    mock_render,
    runner,
    vault,
    tmp_path,
    monkeypatch,
):
    """A root file whose sha is already in a type dir is dropped, no OCR/classify."""
    monkeypatch.delenv("OBAGENT_CONSUME_PREHOOK", raising=False)
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    pdf = inbox / "dup.pdf"
    pdf.write_bytes(b"dup content")
    sha = hashlib.sha256(b"dup content").hexdigest()
    # Pre-seed the asset under a type dir.
    (vault / "Documents" / ASSETS_DIR / sha / "src").mkdir(parents=True)

    result = _invoke(inbox, vault, runner)

    assert result.exit_code == 0, result.output
    assert "Already consumed" in result.output
    assert not pdf.exists()  # redundant inbox copy removed
    mock_ocr.assert_not_called()
    mock_classify.assert_not_called()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.classify_document")
@patch("commands.consume.run_ocr")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_failure_keeps_root_file_and_cleans_staging(
    mock_mistral,
    mock_openai,
    mock_ocr,
    mock_classify,
    mock_llm,
    mock_render,
    runner,
    vault,
    tmp_path,
    monkeypatch,
):
    """OCR failure during classification leaves the root file for retry; staging cleaned."""
    monkeypatch.delenv("OBAGENT_CONSUME_PREHOOK", raising=False)
    _setup_ctx_managers(mock_mistral, mock_openai)
    mock_ocr.side_effect = Exception("Status 502")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    pdf = inbox / "loose.pdf"
    pdf.write_bytes(b"loose content")

    result = _invoke(inbox, vault, runner)

    assert result.exit_code != 0
    assert "Classify failed" in result.output
    assert pdf.exists()  # kept for retry
    assert not (vault / ".obagent" / "staging").exists()  # staging cleaned
    mock_classify.assert_not_called()
