from pathlib import Path
from unittest.mock import patch

import pytest

import commands.bank_statement.pipeline  # noqa: F401 — triggers Pipeline registration
import commands.document.pipeline  # noqa: F401
import commands.receipt.pipeline  # noqa: F401

from commands.bank_statement.pipeline import bank_statement_pipeline
from commands.document.pipeline import document_pipeline
from commands.receipt.pipeline import receipt_pipeline

from tests.conftest import BOTH_KEYS


def _setup_ctx_managers(mock_mistral, mock_openai):
    for mock in (mock_mistral, mock_openai):
        mock.return_value.__enter__ = lambda self: self
        mock.return_value.__exit__ = lambda self, *args: False


# (pipeline, vault_subdir)
CASES = [
    (document_pipeline, "Documents"),
    (receipt_pipeline, "Receipts"),
    (bank_statement_pipeline, "Bank Statements"),
]


@pytest.mark.parametrize("pipeline,path", CASES)
@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_env_var_supplies_input_dir_when_paths_omitted(
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
    pipeline,
    path,
):
    """OBAGENT_CONSUME=/inbox + no PATHS → consume from /inbox/{path}/."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    inbox = tmp_path / "inbox" / path
    inbox.mkdir(parents=True)
    (inbox / "scan.pdf").write_bytes(b"data")
    mock_ingest.return_value = vault / path / "sha"
    monkeypatch.setenv("OBAGENT_CONSUME", str(tmp_path / "inbox"))

    result = runner.invoke(
        pipeline.consume_command,
        list(BOTH_KEYS),
        obj={"vault": str(vault), "path": path},
    )

    assert result.exit_code == 0, result.output
    # Source resolution found the env-var inbox's file.
    mock_ingest.assert_called_once()
    consumed_source = mock_ingest.call_args.args[0]
    assert Path(consumed_source) == inbox / "scan.pdf"
    assert "1 files found: 1 consumed" in result.output


@pytest.mark.parametrize("pipeline,path", CASES)
@patch("commands.consume.render_note")
@patch("commands.consume.extract_fields")
@patch("commands.consume.run_ocr")
@patch("commands.consume.ingest_source")
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_positional_paths_win_over_env_var(
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
    pipeline,
    path,
):
    """When PATHS are given, env-var inbox is ignored."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    # Env-var inbox has a "decoy" file we expect NOT to be consumed.
    env_inbox = tmp_path / "env-inbox" / path
    env_inbox.mkdir(parents=True)
    (env_inbox / "decoy.pdf").write_bytes(b"decoy")
    monkeypatch.setenv("OBAGENT_CONSUME", str(tmp_path / "env-inbox"))
    # Positional PATHS point at a different dir with one real file.
    real = tmp_path / "real-inbox"
    real.mkdir()
    (real / "scan.pdf").write_bytes(b"real")
    mock_ingest.return_value = vault / path / "sha"

    result = runner.invoke(
        pipeline.consume_command,
        [*BOTH_KEYS, str(real)],
        obj={"vault": str(vault), "path": path},
    )

    assert result.exit_code == 0, result.output
    mock_ingest.assert_called_once()
    consumed_source = mock_ingest.call_args.args[0]
    assert Path(consumed_source).name == "scan.pdf"
    assert "decoy" not in str(consumed_source)


@pytest.mark.parametrize("pipeline,path", CASES)
def test_no_paths_and_no_env_var_raises_usage_error(
    runner, vault, monkeypatch, pipeline, path
):
    """With neither PATHS nor OBAGENT_CONSUME, command errors with a helpful message."""
    monkeypatch.delenv("OBAGENT_CONSUME", raising=False)

    result = runner.invoke(
        pipeline.consume_command,
        list(BOTH_KEYS),
        obj={"vault": str(vault), "path": path},
    )

    assert result.exit_code != 0
    assert "OBAGENT_CONSUME" in result.output
    assert "--input-dir" in result.output


@pytest.mark.parametrize("pipeline,path", CASES)
@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_env_var_inbox_missing_subdir_is_soft_skip(
    mock_mistral,
    mock_openai,
    runner,
    vault,
    tmp_path,
    monkeypatch,
    pipeline,
    path,
):
    """OBAGENT_CONSUME set but $INPUT_DIR/{path}/ missing → warn, exit 0."""
    _setup_ctx_managers(mock_mistral, mock_openai)
    monkeypatch.setenv("OBAGENT_CONSUME", str(tmp_path / "empty-root"))

    result = runner.invoke(
        pipeline.consume_command,
        list(BOTH_KEYS),
        obj={"vault": str(vault), "path": path},
    )

    assert result.exit_code == 0, result.output
    assert "No inbox at" in result.output
    assert path in result.output
    # Clients should not have been opened for a no-op run.
    mock_mistral.assert_not_called()
    mock_openai.assert_not_called()
