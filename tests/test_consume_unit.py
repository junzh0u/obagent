from pathlib import Path
from unittest.mock import call, patch

from commands.consume import consume

from tests.conftest import BOTH_KEYS


@patch("commands.consume.extract_title")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_calls_all_three_steps(
    mock_ingest, mock_ocr, mock_llm, runner, vault, source_dir
):
    """consume calls ingest_pdf, run_ocr, and extract_title in sequence."""
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    target_dir = vault / "papers" / "sha"
    mock_ingest.return_value = target_dir
    mock_ocr.return_value = "ocr text"

    result = runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    mock_ingest.assert_called_once()
    mock_ocr.assert_called_once_with(target_dir, "test-key", overwrite=False)
    mock_llm.assert_called_once_with(
        target_dir, "test-oai-key", "ocr text", "papers", overwrite=False
    )


@patch("commands.consume.extract_title")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_skips_ocr_and_llm_when_ingest_returns_none(
    mock_ingest, mock_ocr, mock_llm, runner, vault, source_dir
):
    """When ingest_pdf returns None (duplicate), OCR and LLM are skipped."""
    pdf = source_dir / "dup.pdf"
    pdf.write_bytes(b"dup")
    mock_ingest.return_value = None

    result = runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    mock_ingest.assert_called_once()
    mock_ocr.assert_not_called()
    mock_llm.assert_not_called()


@patch("commands.consume.extract_title")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_handles_llm_exception(
    mock_ingest, mock_ocr, mock_llm, runner, vault, source_dir
):
    """LLM exceptions are caught and printed as warnings."""
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    mock_ingest.return_value = vault / "papers" / "sha"
    mock_ocr.return_value = "ocr text"
    mock_llm.side_effect = ValueError("API error")

    result = runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert "Warning: title extraction failed: API error" in result.output


@patch("commands.consume.extract_title")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_forwards_flags(mock_ingest, mock_ocr, mock_llm, runner, vault, source_dir):
    """--keep-original and --overwrite are forwarded to sub-functions."""
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"test")
    target_dir = vault / "papers" / "sha"
    mock_ingest.return_value = target_dir
    mock_ocr.return_value = "ocr text"

    result = runner.invoke(
        consume,
        [
            "--path",
            "papers",
            "--keep-original",
            "--overwrite",
            *BOTH_KEYS,
            str(source_dir),
        ],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    ingest_kwargs = mock_ingest.call_args
    assert ingest_kwargs.kwargs["keep_original"] is True
    assert ingest_kwargs.kwargs["overwrite"] is True
    mock_ocr.assert_called_once_with(target_dir, "test-key", overwrite=True)
    mock_llm.assert_called_once_with(
        target_dir, "test-oai-key", "ocr text", "papers", overwrite=True
    )


@patch("commands.consume.extract_title")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_processes_multiple_pdfs(
    mock_ingest, mock_ocr, mock_llm, runner, vault, source_dir
):
    """Multiple PDFs are each processed through all 3 steps."""
    for name in ["a.pdf", "b.pdf", "c.pdf"]:
        (source_dir / name).write_bytes(name.encode())

    dirs = [vault / "papers" / f"sha_{i}" for i in range(3)]
    mock_ingest.side_effect = dirs
    mock_ocr.return_value = "ocr text"

    result = runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert mock_ingest.call_count == 3
    assert mock_ocr.call_count == 3
    assert mock_llm.call_count == 3


@patch("commands.consume.extract_title")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_pdf")
def test_no_pdfs_does_nothing(
    mock_ingest, mock_ocr, mock_llm, runner, vault, source_dir
):
    """An empty source directory calls nothing."""
    result = runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    mock_ingest.assert_not_called()
    mock_ocr.assert_not_called()
    mock_llm.assert_not_called()
