from unittest.mock import patch

from commands.bank_statement.consume import consume
from commands.bank_statement.llm import _prompt
from commands.bank_statement.render import (
    FIELD_DEFAULTS,
    format_frontmatter,
    make_title,
)
from constants import LLM_MODEL, OCR_MODEL

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
    target_dir = vault / "statements" / "sha"
    mock_ingest.return_value = target_dir
    result = runner.invoke(
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    mock_ingest.assert_called_once()
    mock_ocr.assert_called_once_with(
        target_dir, mock_mistral.return_value, model=OCR_MODEL, overwrite=False
    )
    mock_llm.assert_called_once()
    llm_kwargs = mock_llm.call_args
    assert llm_kwargs.kwargs["prompt_fn"] is _prompt
    assert llm_kwargs.kwargs["model"] == LLM_MODEL
    assert llm_kwargs.kwargs["overwrite"] is False
    mock_render.assert_called_once()
    render_kwargs = mock_render.call_args
    assert render_kwargs.kwargs["field_defaults"] is FIELD_DEFAULTS
    assert render_kwargs.kwargs["make_title"] is make_title
    assert render_kwargs.kwargs["format_frontmatter"] is format_frontmatter
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
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    mock_ocr.assert_not_called()
    mock_llm.assert_not_called()
    mock_render.assert_not_called()
    assert "1 files found: 0 consumed, 1 already in vault" in result.output


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_aborts_on_ocr_exception(
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
    """OCR exceptions abort the command."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    mock_ingest.return_value = vault / "statements" / "sha"
    mock_ocr.side_effect = Exception("Status 502")

    result = runner.invoke(
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code != 0
    assert "OCR failed: Status 502" in result.output
    mock_llm.assert_not_called()
    mock_render.assert_not_called()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_handles_render_warning(
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
    """Render exceptions are caught and printed as warnings."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    mock_ingest.return_value = vault / "statements" / "sha"
    mock_render.side_effect = ValueError("Template error")

    result = runner.invoke(
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    assert "Warning: note rendering failed: Template error" in result.output
    mock_llm.assert_called_once()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_forwards_flags(
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
    """--keep-original and --overwrite are forwarded to sub-functions."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    target_dir = vault / "statements" / "sha"
    mock_ingest.return_value = target_dir

    result = runner.invoke(
        consume,
        [
            "--keep-original",
            "--overwrite",
            "--ocr-model",
            "custom-ocr",
            "--llm-model",
            "custom-llm",
            *BOTH_KEYS,
            str(source_dir),
        ],
        obj={"vault": str(vault), "path": "statements"},
    )

    assert result.exit_code == 0
    ingest_kwargs = mock_ingest.call_args
    assert ingest_kwargs.kwargs["keep_original"] is True
    assert ingest_kwargs.kwargs["overwrite"] is True
    mock_ocr.assert_called_once_with(
        target_dir, mock_mistral.return_value, model="custom-ocr", overwrite=True
    )
    llm_kwargs = mock_llm.call_args
    assert llm_kwargs.kwargs["model"] == "custom-llm"
    assert llm_kwargs.kwargs["overwrite"] is True
    render_kwargs = mock_render.call_args
    assert render_kwargs.kwargs["overwrite"] is True
