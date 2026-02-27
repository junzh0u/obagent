from unittest.mock import patch

from commands.receipt.pipeline import receipt_pipeline
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
    """consume calls ingest_source, run_ocr, extract_fields, and render_note in sequence."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    target_dir = vault / "papers" / "sha"
    mock_ingest.return_value = target_dir
    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    mock_mistral.assert_called_once_with(api_key="test-key")
    mock_openai.assert_called_once_with(api_key="test-oai-key")
    mock_ingest.assert_called_once()
    mock_ocr.assert_called_once_with(
        target_dir, mock_mistral.return_value, model=OCR_MODEL, overwrite=False
    )
    mock_llm.assert_called_once_with(
        target_dir,
        mock_openai.return_value,
        "papers",
        model=LLM_MODEL,
        overwrite=False,
        pipeline=receipt_pipeline,
    )
    mock_render.assert_called_once_with(
        target_dir,
        overwrite=False,
        note_index=None,
        pipeline=receipt_pipeline,
    )
    assert "1 files found: 1 consumed, 0 already in vault" in result.output


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_skips_ocr_llm_render_when_ingest_returns_none(
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
    """When ingest_source returns None (duplicate), OCR, LLM, and render are skipped."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    pdf = source_dir / "dup.pdf"
    pdf.write_bytes(b"dup")
    mock_ingest.return_value = None

    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    mock_ingest.assert_called_once()
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
    mock_ingest.return_value = vault / "papers" / "sha"

    mock_ocr.side_effect = Exception("Status 502")

    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
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
def test_aborts_on_llm_exception(
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
    """LLM exceptions abort the command."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    mock_ingest.return_value = vault / "papers" / "sha"

    mock_llm.side_effect = ValueError("API error")

    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code != 0
    assert "Field extraction failed: API error" in result.output
    mock_render.assert_not_called()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_handles_render_exception(
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
    mock_ingest.return_value = vault / "papers" / "sha"

    mock_render.side_effect = ValueError("Template error")

    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
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
    target_dir = vault / "papers" / "sha"
    mock_ingest.return_value = target_dir

    result = runner.invoke(
        receipt_pipeline.consume_command,
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
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    ingest_kwargs = mock_ingest.call_args
    assert ingest_kwargs.kwargs["keep_original"] is True
    assert ingest_kwargs.kwargs["overwrite"] is True
    mock_ocr.assert_called_once_with(
        target_dir, mock_mistral.return_value, model="custom-ocr", overwrite=True
    )
    mock_llm.assert_called_once_with(
        target_dir,
        mock_openai.return_value,
        "papers",
        model="custom-llm",
        overwrite=True,
        pipeline=receipt_pipeline,
    )
    mock_render.assert_called_once_with(
        target_dir,
        overwrite=True,
        note_index={},
        pipeline=receipt_pipeline,
    )


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_processes_multiple_files(
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
    """Multiple files are each processed through all 4 steps."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    for name in ["a.pdf", "b.pdf", "c.pdf"]:
        (source_dir / name).write_bytes(name.encode())

    dirs = [vault / "papers" / f"sha_{i}" for i in range(3)]
    mock_ingest.side_effect = dirs

    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert mock_ingest.call_count == 3
    assert mock_ocr.call_count == 3
    assert mock_llm.call_count == 3
    assert mock_render.call_count == 3
    assert "3 files found: 3 consumed, 0 already in vault" in result.output


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_no_files_does_nothing(
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
    """An empty source directory calls nothing."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    mock_ingest.assert_not_called()
    mock_ocr.assert_not_called()
    mock_llm.assert_not_called()
    mock_render.assert_not_called()
    assert "0 files found: 0 consumed, 0 already in vault" in result.output
