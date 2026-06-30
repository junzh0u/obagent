"""--purge-queue / OBAGENT_PURGE_QUEUE: copy-mode + record consumed paths for a
host-side drain (Cloud Sync can't see the container's own deletes)."""

from unittest.mock import patch

from commands.consume import consume_all
from commands.receipt.pipeline import receipt_pipeline

from tests.conftest import BOTH_KEYS


def _setup_ctx_managers(mock_mistral, mock_openai):
    for mock in (mock_mistral, mock_openai):
        mock.return_value.__enter__ = lambda self: self
        mock.return_value.__exit__ = lambda self, *args: False


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_purge_queue_copies_and_records(
    mock_mistral, mock_openai, mock_ocr, mock_llm, mock_render, runner, vault, tmp_path
):
    """--purge-queue copies the source (leaves it in place) and appends its path."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    source_dir = tmp_path / "inbox"
    source_dir.mkdir()
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"queue me")
    queue = tmp_path / "purge-queue" / "queue"

    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, "--purge-queue", str(queue), str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0, result.output
    # Copied, not moved: the source survives for the host job to delete.
    assert pdf.exists()
    # Its resolved path is recorded, one line.
    assert queue.read_text().splitlines() == [str(pdf.resolve())]


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_purge_queue_records_duplicate(
    mock_mistral, mock_openai, mock_ocr, mock_llm, mock_render, runner, vault, tmp_path
):
    """An already-consumed (duplicate) source is still recorded — so a re-downloaded
    file that was already ingested still gets drained."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    source_dir = tmp_path / "inbox"
    source_dir.mkdir()
    pdf = source_dir / "dup.pdf"
    pdf.write_bytes(b"same bytes")
    queue = tmp_path / "purge-queue" / "queue"
    args = [*BOTH_KEYS, "--purge-queue", str(queue), str(source_dir)]
    obj = {"vault": str(vault), "path": "papers"}

    # First pass ingests it.
    runner.invoke(receipt_pipeline.consume_command, args, obj=obj)
    # Second pass sees the sha already in the vault -> duplicate -> still recorded.
    result = runner.invoke(receipt_pipeline.consume_command, args, obj=obj)

    assert result.exit_code == 0, result.output
    assert "already in vault" in result.output
    assert pdf.exists()
    # One line per pass (append-only); both the same resolved path.
    assert queue.read_text().splitlines() == [str(pdf.resolve())] * 2


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_purge_queue_not_recorded_on_failure(
    mock_mistral, mock_openai, mock_ocr, mock_llm, mock_render, runner, vault, tmp_path
):
    """A mid-pipeline failure (OCR raises) leaves the source un-recorded — so a failed
    consume keeps the inbox file for a clean retry."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    mock_ocr.side_effect = Exception("Status 502")
    source_dir = tmp_path / "inbox"
    source_dir.mkdir()
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"will fail ocr")
    queue = tmp_path / "purge-queue" / "queue"

    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, "--purge-queue", str(queue), str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code != 0
    assert "OCR failed" in result.output
    assert pdf.exists()  # source still in the inbox for retry
    assert not queue.exists()  # nothing recorded


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_no_purge_queue_moves_and_records_nothing(
    mock_mistral, mock_openai, mock_ocr, mock_llm, mock_render, runner, vault, tmp_path
):
    """Without --purge-queue, behavior is unchanged: the source is moved, no queue."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    source_dir = tmp_path / "inbox"
    source_dir.mkdir()
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"move me")
    queue = tmp_path / "purge-queue" / "queue"

    result = runner.invoke(
        receipt_pipeline.consume_command,
        [*BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0, result.output
    assert not pdf.exists()  # moved out
    assert not queue.exists()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_purge_queue_threads_through_consume_all(
    mock_mistral,
    mock_openai,
    mock_ingest,
    mock_ocr,
    mock_llm,
    mock_render,
    runner,
    vault,
    tmp_path,
    monkeypatch,
):
    """The top-level `obagent consume` aggregator also honors --purge-queue."""
    monkeypatch.delenv("OBAGENT_CONSUME_PREHOOK", raising=False)
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    (inbox / "Receipts").mkdir(parents=True)
    pdf = inbox / "Receipts" / "scan.pdf"
    pdf.write_bytes(b"data")
    queue = tmp_path / "purge-queue" / "queue"
    # ingest copies in real life; mock returns a target so the path is recorded.
    mock_ingest.return_value = vault / "Receipts" / "sha"

    result = runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox), "--purge-queue", str(queue)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0, result.output
    # ingest_source forced into copy mode (keep_original=True) by the queue.
    assert all(c.kwargs["keep_original"] is True for c in mock_ingest.call_args_list)
    assert str(pdf.resolve()) in queue.read_text().splitlines()
