from pathlib import Path
from unittest.mock import patch

import commands.bank_statement.pipeline  # noqa: F401 — triggers Pipeline registration
import commands.document.pipeline  # noqa: F401
import commands.receipt.pipeline  # noqa: F401

from commands.consume import consume_all

from tests.conftest import BOTH_KEYS


def _setup_ctx_managers(mock_mistral, mock_openai):
    for mock in (mock_mistral, mock_openai):
        mock.return_value.__enter__ = lambda self: self
        mock.return_value.__exit__ = lambda self, *args: False


def _ingest_returns_target(call_count: list[int], vault: Path):
    """ingest_source side_effect: returns a unique fake target_dir per call."""

    def _side_effect(source, vault_arg, path, **kwargs):
        call_count[0] += 1
        return vault_arg / path / f"sha-{call_count[0]}"

    return _side_effect


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_consumes_every_type_from_input_dir(
    mock_mistral,
    mock_openai,
    mock_ingest,
    mock_ocr,
    mock_llm,
    mock_render,
    runner,
    vault,
    tmp_path,
):
    """A single `obagent consume` ingests files from each type's subdir."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    for path in ("Documents", "Receipts", "Bank Statements"):
        (inbox / path).mkdir(parents=True)
        (inbox / path / "scan.pdf").write_bytes(b"data")
    mock_ingest.side_effect = _ingest_returns_target([0], vault)

    result = runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0, result.output
    # At least one ingest call per type. (Other tests can pollute Pipeline._registry
    # with extra entries, so we check the set of consumed dirs rather than exact count.)
    assert mock_ingest.call_count >= 3
    consumed_sources = [Path(c.args[0]) for c in mock_ingest.call_args_list]
    consumed_dirs = {p.parent.name for p in consumed_sources}
    assert consumed_dirs == {"Documents", "Receipts", "Bank Statements"}


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_prints_section_header_per_type(
    mock_mistral,
    mock_openai,
    mock_ingest,
    mock_ocr,
    mock_llm,
    mock_render,
    runner,
    vault,
    tmp_path,
):
    """Each type produces a `=== <Path> ===` banner."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    (inbox / "Documents").mkdir(parents=True)
    (inbox / "Documents" / "scan.pdf").write_bytes(b"data")
    mock_ingest.side_effect = _ingest_returns_target([0], vault)

    result = runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0, result.output
    assert "=== Documents ===" in result.output
    assert "=== Receipts ===" in result.output
    assert "=== Bank Statements ===" in result.output


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_missing_type_inbox_is_soft_skip(
    mock_mistral,
    mock_openai,
    mock_ingest,
    mock_ocr,
    mock_llm,
    mock_render,
    runner,
    vault,
    tmp_path,
):
    """Types with no inbox subdir log a warning and continue."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    # Only Documents/ exists; Receipts/ and Bank Statements/ are missing.
    (inbox / "Documents").mkdir(parents=True)
    (inbox / "Documents" / "scan.pdf").write_bytes(b"data")
    mock_ingest.side_effect = _ingest_returns_target([0], vault)

    result = runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0, result.output
    # Only Documents had a file. Other types log "No inbox" and skip.
    # (Documents may appear in Pipeline._registry multiple times due to other
    # tests instantiating DocumentPipeline; that's fine — same inbox, same file.)
    consumed_sources = {Path(c.args[0]) for c in mock_ingest.call_args_list}
    assert all(p.parent.name == "Documents" for p in consumed_sources)
    assert len(consumed_sources) == 1
    # Skip warnings appear for the missing types.
    assert "No inbox at" in result.output
    assert "Receipts" in result.output
    assert "Bank Statements" in result.output


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_env_var_supplies_input_dir(
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
    """OBAGENT_CONSUME is used when --input-dir is omitted."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    (inbox / "Receipts").mkdir(parents=True)
    (inbox / "Receipts" / "scan.pdf").write_bytes(b"data")
    mock_ingest.side_effect = _ingest_returns_target([0], vault)
    monkeypatch.setenv("OBAGENT_CONSUME", str(inbox))

    result = runner.invoke(consume_all, list(BOTH_KEYS), obj={"vault": str(vault)})

    assert result.exit_code == 0, result.output
    assert mock_ingest.call_count == 1
    consumed_source = Path(mock_ingest.call_args.args[0])
    assert consumed_source == inbox / "Receipts" / "scan.pdf"


def test_missing_input_dir_and_env_var_errors(runner, vault, monkeypatch):
    """Without --input-dir and OBAGENT_CONSUME unset, click errors."""
    monkeypatch.delenv("OBAGENT_CONSUME", raising=False)

    result = runner.invoke(consume_all, list(BOTH_KEYS), obj={"vault": str(vault)})

    assert result.exit_code != 0
    assert "--input-dir" in result.output


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_prehook_runs_before_consume(
    mock_mistral,
    mock_openai,
    mock_ingest,
    mock_ocr,
    mock_llm,
    mock_render,
    runner,
    vault,
    tmp_path,
):
    """--prehook fires before the per-type loop and its side effects are visible."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    seed = tmp_path / "scan.pdf"
    seed.write_bytes(b"data")
    # Hook populates the Documents/ subdir that doesn't exist yet at invocation time.
    hook = f'mkdir -p "{inbox}/Documents" && cp "{seed}" "{inbox}/Documents/"'
    mock_ingest.side_effect = _ingest_returns_target([0], vault)

    result = runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox), "--prehook", hook],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0, result.output
    assert "=== Prehook ===" in result.output
    # The hook created Documents/scan.pdf and consume picked it up.
    # (Documents may appear multiple times in Pipeline._registry due to suite-wide
    # pollution; we just check the file was consumed at least once from the
    # right place.)
    consumed_sources = {Path(c.args[0]) for c in mock_ingest.call_args_list}
    assert consumed_sources == {inbox / "Documents" / "scan.pdf"}


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_prehook_failure_aborts_consume(
    mock_mistral, mock_openai, runner, vault, tmp_path
):
    """A non-zero prehook aborts before clients are opened or files consumed."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    (inbox / "Documents").mkdir(parents=True)
    (inbox / "Documents" / "scan.pdf").write_bytes(b"data")

    result = runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox), "--prehook", "false"],
        obj={"vault": str(vault)},
    )

    assert result.exit_code != 0
    assert "Prehook failed" in result.output
    # Clients should never have been opened.
    mock_mistral.assert_not_called()
    mock_openai.assert_not_called()


@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_prehook_env_var_default(
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
    """OBAGENT_CONSUME_PREHOOK supplies the hook when --prehook is omitted."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox"
    (inbox / "Documents").mkdir(parents=True)
    (inbox / "Documents" / "scan.pdf").write_bytes(b"data")
    mock_ingest.side_effect = _ingest_returns_target([0], vault)
    monkeypatch.setenv("OBAGENT_CONSUME_PREHOOK", "echo prehook-marker")

    result = runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0, result.output
    assert "=== Prehook ===" in result.output
    assert "prehook-marker" in result.output
    # The actual consume still ran (>=1 because registry pollution from other tests).
    assert mock_ingest.call_count >= 1
