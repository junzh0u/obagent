from unittest.mock import patch

from commands.consume import consume
from constants import LLM_MODEL, OCR_MODEL

from tests.conftest import BOTH_KEYS


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_calls_all_four_steps(
    mock_ingest, mock_ocr, mock_llm, mock_render, runner, vault, source_dir
):
    """consume calls ingest_pdf, run_ocr, extract_fields, and render_note in sequence."""
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    target_dir = vault / "papers" / "sha"
    mock_ingest.return_value = target_dir
    result = runner.invoke(
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    mock_ingest.assert_called_once()
    mock_ocr.assert_called_once_with(
        target_dir, "test-key", model=OCR_MODEL, overwrite=False
    )
    mock_llm.assert_called_once_with(
        target_dir,
        "test-oai-key",
        "papers",
        model=LLM_MODEL,
        overwrite=False,
    )
    mock_render.assert_called_once_with(target_dir)


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_skips_ocr_llm_render_when_ingest_returns_none(
    mock_ingest, mock_ocr, mock_llm, mock_render, runner, vault, source_dir
):
    """When ingest_pdf returns None (duplicate), OCR, LLM, and render are skipped."""
    pdf = source_dir / "dup.pdf"
    pdf.write_bytes(b"dup")
    mock_ingest.return_value = None

    result = runner.invoke(
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    mock_ingest.assert_called_once()
    mock_ocr.assert_not_called()
    mock_llm.assert_not_called()
    mock_render.assert_not_called()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_handles_llm_exception(
    mock_ingest, mock_ocr, mock_llm, mock_render, runner, vault, source_dir
):
    """LLM exceptions are caught, render is skipped for that entry."""
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    mock_ingest.return_value = vault / "papers" / "sha"

    mock_llm.side_effect = ValueError("API error")

    result = runner.invoke(
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Warning: field extraction failed: API error" in result.output
    mock_render.assert_not_called()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_handles_render_exception(
    mock_ingest, mock_ocr, mock_llm, mock_render, runner, vault, source_dir
):
    """Render exceptions are caught and printed as warnings."""
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    mock_ingest.return_value = vault / "papers" / "sha"

    mock_render.side_effect = ValueError("Template error")

    result = runner.invoke(
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Warning: note rendering failed: Template error" in result.output
    mock_llm.assert_called_once()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_forwards_flags(
    mock_ingest, mock_ocr, mock_llm, mock_render, runner, vault, source_dir
):
    """--keep-original and --overwrite are forwarded to sub-functions."""
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    target_dir = vault / "papers" / "sha"
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
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    ingest_kwargs = mock_ingest.call_args
    assert ingest_kwargs.kwargs["keep_original"] is True
    assert ingest_kwargs.kwargs["overwrite"] is True
    mock_ocr.assert_called_once_with(
        target_dir, "test-key", model="custom-ocr", overwrite=True
    )
    mock_llm.assert_called_once_with(
        target_dir,
        "test-oai-key",
        "papers",
        model="custom-llm",
        overwrite=True,
    )
    mock_render.assert_called_once_with(target_dir)


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_processes_multiple_pdfs(
    mock_ingest, mock_ocr, mock_llm, mock_render, runner, vault, source_dir
):
    """Multiple PDFs are each processed through all 4 steps."""
    for name in ["a.pdf", "b.pdf", "c.pdf"]:
        (source_dir / name).write_bytes(name.encode())

    dirs = [vault / "papers" / f"sha_{i}" for i in range(3)]
    mock_ingest.side_effect = dirs

    result = runner.invoke(
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert mock_ingest.call_count == 3
    assert mock_ocr.call_count == 3
    assert mock_llm.call_count == 3
    assert mock_render.call_count == 3


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_no_pdfs_does_nothing(
    mock_ingest, mock_ocr, mock_llm, mock_render, runner, vault, source_dir
):
    """An empty source directory calls nothing."""
    result = runner.invoke(
        consume,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    mock_ingest.assert_not_called()
    mock_ocr.assert_not_called()
    mock_llm.assert_not_called()
    mock_render.assert_not_called()
