"""Sources that keep failing consume are moved to {inbox}/_failed/."""

import hashlib
import json
from unittest.mock import patch

import pytest

import obagent.commands.bank_statement.pipeline  # noqa: F401 — register pipelines
import obagent.commands.document.pipeline  # noqa: F401
import obagent.commands.receipt.pipeline  # noqa: F401
from obagent.commands.consume import consume_all
from obagent.commands.quarantine import FAILURES_FILE, Quarantine

from tests.conftest import BOTH_KEYS


@pytest.fixture(autouse=True)
def _ctx_managers(monkeypatch):
    monkeypatch.delenv("OBAGENT_CONSUME_PREHOOK", raising=False)
    monkeypatch.delenv("OBAGENT_CONSUME_MAX_ATTEMPTS", raising=False)
    for name in ("Mistral", "OpenAI"):
        mock = patch(f"obagent.commands.consume.{name}").start()
        mock.return_value.__enter__ = lambda self: self
        mock.return_value.__exit__ = lambda self, *args: False
    yield
    patch.stopall()


def _run(runner, vault, inbox, *extra):
    return runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox), "--no-classify", *extra],
        obj={"vault": str(vault)},
    )


def _failures(vault):
    path = vault / FAILURES_FILE
    return json.loads(path.read_text()) if path.exists() else {}


@pytest.fixture
def inbox_file(tmp_path):
    f = tmp_path / "inbox" / "Documents" / "scan.pdf"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"scan")
    return f


SHA = hashlib.sha256(b"scan").hexdigest()


@patch("obagent.commands.consume.render_note")
@patch("obagent.commands.consume.extract_fields")
@patch("obagent.commands.consume.run_ocr", side_effect=Exception("Status 400"))
def test_moved_after_max_attempts(_ocr, _llm, _render, runner, vault, inbox_file):
    inbox = inbox_file.parents[1]
    for attempt in (1, 2):
        result = _run(runner, vault, inbox, "--max-attempts", "3")
        assert result.exit_code == 1, result.output
        assert inbox_file.exists()
        assert _failures(vault)[SHA]["attempts"] == attempt

    result = _run(runner, vault, inbox, "--max-attempts", "3")

    assert result.exit_code == 1, result.output
    moved = inbox / "_failed" / "scan.pdf"
    assert moved.read_bytes() == b"scan" and not inbox_file.exists()
    note = (inbox / "_failed" / "scan.pdf.error.txt").read_text()
    assert "failed 3 consume attempts in a row" in note
    assert "OCR failed: Status 400" in note and str(inbox_file) in note
    # The pass output carries everything the operator needs.
    assert "Quarantined: scan.pdf" in result.output
    assert "OCR failed: Status 400" in result.output
    assert "moved to" in result.output
    assert SHA not in _failures(vault)  # a file moved back starts afresh

    # _failed/ is never scanned: the next run doesn't see it.
    result = _run(runner, vault, inbox, "--max-attempts", "3")
    assert result.exit_code == 0, result.output
    assert moved.exists()


@patch("obagent.commands.consume.render_note")
@patch("obagent.commands.consume.extract_fields")
@patch("obagent.commands.consume.run_ocr")
def test_success_clears_the_count(mock_ocr, _llm, _render, runner, vault, inbox_file):
    inbox = inbox_file.parents[1]
    mock_ocr.side_effect = Exception("Status 503")
    _run(runner, vault, inbox)
    assert _failures(vault)[SHA]["attempts"] == 1

    mock_ocr.side_effect = None
    result = _run(runner, vault, inbox)

    assert result.exit_code == 0, result.output
    assert not (vault / FAILURES_FILE).exists()


@pytest.mark.parametrize("extra", [["--max-attempts", "0"], ["--keep-original"]])
@patch("obagent.commands.consume.render_note")
@patch("obagent.commands.consume.extract_fields")
@patch("obagent.commands.consume.run_ocr", side_effect=Exception("boom"))
def test_quarantine_off(_ocr, _llm, _render, extra, runner, vault, inbox_file):
    inbox = inbox_file.parents[1]
    for _ in range(2):
        _run(runner, vault, inbox, "--max-attempts", "1", *extra)
    assert inbox_file.exists()
    assert not (inbox / "_failed").exists()


def test_name_collision_gets_sha_suffix(tmp_path, vault):
    inbox = tmp_path / "inbox"
    (inbox / "_failed").mkdir(parents=True)
    (inbox / "_failed" / "scan.pdf").write_bytes(b"older")
    src = inbox / "scan.pdf"
    src.write_bytes(b"scan")
    q = Quarantine(vault, inbox, 1)

    q.failed(src, SHA, "boom")

    assert (inbox / "_failed" / f"scan-{SHA[:12]}.pdf").read_bytes() == b"scan"
    assert (inbox / "_failed" / "scan.pdf").read_bytes() == b"older"
