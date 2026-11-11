"""Consume builds each new asset in staging and commits it only when complete."""

import hashlib
from unittest.mock import patch

import pytest

import obagent.commands.bank_statement.pipeline  # noqa: F401 — register pipelines
import obagent.commands.document.pipeline  # noqa: F401
import obagent.commands.receipt.pipeline  # noqa: F401
from obagent.commands.consume import STAGING_PATH, consume_all
from obagent.commands.receipt.pipeline import receipt_pipeline
from obagent.lib.constants import ASSETS_DIR

from tests.conftest import BOTH_KEYS


@pytest.fixture(autouse=True)
def _ctx_managers(monkeypatch):
    monkeypatch.delenv("OBAGENT_CONSUME_PREHOOK", raising=False)
    for name in ("Mistral", "OpenAI"):
        patcher = patch(f"obagent.commands.consume.{name}")
        mock = patcher.start()
        mock.return_value.__enter__ = lambda self: self
        mock.return_value.__exit__ = lambda self, *args: False
    yield
    patch.stopall()


def _invoke(runner, vault, inbox, *extra):
    return runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox), *extra],
        obj={"vault": str(vault)},
    )


def _asset(vault, path, data):
    return vault / path / ASSETS_DIR / hashlib.sha256(data).hexdigest()


def _inbox_file(tmp_path, rel, data):
    f = tmp_path / "inbox" / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


@pytest.mark.parametrize("failing", ["run_ocr", "extract_fields"])
@patch("obagent.commands.consume.render_note")
@patch("obagent.commands.consume.extract_fields")
@patch("obagent.commands.consume.run_ocr")
def test_typed_failure_leaves_no_asset_and_keeps_the_source(
    mock_ocr, mock_llm, mock_render, failing, runner, vault, tmp_path
):
    """The 2026-11-10 incident: a failed OCR must not strand a src-only asset that
    dedup then skips forever. The source stays in the inbox for a retry."""
    {"run_ocr": mock_ocr, "extract_fields": mock_llm}[failing].side_effect = Exception(
        "Status 400"
    )
    src = _inbox_file(tmp_path, "Documents/scan.pdf", b"scan")

    result = _invoke(runner, vault, tmp_path / "inbox", "--no-classify")

    assert result.exit_code == 1, result.output
    assert "1 source file(s) failed" in result.output
    assert src.exists()
    assert not _asset(vault, "Documents", b"scan").exists()
    assert not (vault / STAGING_PATH).exists()
    mock_render.assert_not_called()


@patch("obagent.commands.consume.render_note")
@patch("obagent.commands.consume.extract_fields")
@patch("obagent.commands.consume.run_ocr")
def test_typed_failure_does_not_block_the_batch(
    mock_ocr, mock_llm, mock_render, runner, vault, tmp_path
):
    mock_ocr.side_effect = [Exception("boom"), None]  # sorted: a.pdf, b.pdf
    bad = _inbox_file(tmp_path, "Documents/a.pdf", b"bad")
    good = _inbox_file(tmp_path, "Documents/b.pdf", b"good")

    result = _invoke(runner, vault, tmp_path / "inbox", "--no-classify")

    assert result.exit_code == 1, result.output
    assert bad.exists() and not good.exists()
    committed = _asset(vault, "Documents", b"good")
    assert (committed / "src" / "original.pdf").read_bytes() == b"good"
    # OCR/LLM ran on the staging copy; render on the committed asset.
    assert STAGING_PATH in str(mock_llm.call_args.args[0])
    assert mock_render.call_args.args[0] == committed


@patch("obagent.commands.consume.render_note")
@patch("obagent.commands.consume.extract_fields")
@patch("obagent.commands.consume.classify_document")
@patch("obagent.commands.consume.run_ocr")
def test_classified_llm_failure_leaves_no_asset(
    mock_ocr, mock_classify, mock_llm, mock_render, runner, vault, tmp_path
):
    """Smart inbox: field extraction now runs before the asset is committed."""
    mock_classify.return_value = receipt_pipeline
    mock_llm.side_effect = Exception("API error")
    src = _inbox_file(tmp_path, "loose.pdf", b"loose")

    result = _invoke(runner, vault, tmp_path / "inbox")

    assert result.exit_code == 1, result.output
    assert "field extraction failed" in result.output
    assert src.exists()
    assert not _asset(vault, "Receipts", b"loose").exists()
    mock_render.assert_not_called()


@patch("obagent.commands.consume.render_note")
@patch("obagent.commands.consume.extract_fields")
@patch("obagent.commands.consume.run_ocr")
def test_crash_leftovers_in_staging_are_cleared(
    mock_ocr, mock_llm, mock_render, runner, vault, tmp_path
):
    """A half-built asset from a killed run sits only in staging, so the next run
    drops it and consumes the still-present source normally."""
    leftover = vault / STAGING_PATH / ASSETS_DIR / "dead" / "src"
    leftover.mkdir(parents=True)
    src = _inbox_file(tmp_path, "Documents/scan.pdf", b"scan")

    result = _invoke(runner, vault, tmp_path / "inbox", "--no-classify")

    assert result.exit_code == 0, result.output
    assert not src.exists()
    assert _asset(vault, "Documents", b"scan").is_dir()
    assert not (vault / STAGING_PATH).exists()
