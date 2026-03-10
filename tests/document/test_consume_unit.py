from unittest.mock import patch

from commands.document.pipeline import document_pipeline
from lib.constants import LLM_MODEL, OCR_MODEL

from tests.conftest import BOTH_KEYS


def _setup_ctx_managers(mock_mistral, mock_openai):
    """Make mock clients support context manager protocol."""
    for mock in (mock_mistral, mock_openai):
        mock.return_value.__enter__ = lambda self: self
        mock.return_value.__exit__ = lambda self, *args: False


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_calls_all_four_steps(
    mock_mistral,
    mock_openai,
    mock_ingest,
    mock_ocr,
    mock_llm,
    mock_render,
    runner,
    vault,
    source_dir,
):
    """consume calls ingest, ocr, extract_fields, and render_note in sequence."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    target_dir = vault / "docs" / "sha"
    mock_ingest.return_value = target_dir
    result = runner.invoke(
        document_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "docs"},
    )

    assert result.exit_code == 0
    mock_ingest.assert_called_once()
    mock_ocr.assert_called_once_with(
        target_dir, mock_mistral.return_value, model=OCR_MODEL, overwrite=False
    )
    mock_llm.assert_called_once()
    llm_kwargs = mock_llm.call_args
    assert llm_kwargs.kwargs["pipeline"] is document_pipeline
    assert llm_kwargs.kwargs["model"] == LLM_MODEL
    assert llm_kwargs.kwargs["overwrite"] is False
    mock_render.assert_called_once()
    render_kwargs = mock_render.call_args
    assert render_kwargs.kwargs["pipeline"] is document_pipeline
    assert "1 files found: 1 consumed, 0 already in vault" in result.output


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_skips_when_ingest_returns_none(
    mock_mistral,
    mock_openai,
    mock_ingest,
    mock_ocr,
    mock_llm,
    mock_render,
    runner,
    vault,
    source_dir,
):
    """When ingest_source returns None, OCR/LLM/render are skipped."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    pdf = source_dir / "dup.pdf"
    pdf.write_bytes(b"dup")
    mock_ingest.return_value = None

    result = runner.invoke(
        document_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "docs"},
    )

    assert result.exit_code == 0
    mock_ocr.assert_not_called()
    mock_llm.assert_not_called()
    mock_render.assert_not_called()
    assert "1 files found: 0 consumed, 1 already in vault" in result.output
