from pathlib import Path
from unittest.mock import patch

import pytest

import obagent.commands.document.pipeline  # noqa: F401 — triggers Pipeline registration
from obagent.commands.consume import _filter_intact, _is_truncated, consume_all

from tests.conftest import BOTH_KEYS

pytestmark = pytest.mark.real_pdf_check

COMPLETE = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_complete_pdf_is_intact(tmp_path):
    assert not _is_truncated(_write(tmp_path / "a.pdf", COMPLETE))


def test_trailing_junk_after_eof_is_intact(tmp_path):
    pdf = _write(tmp_path / "a.PDF", COMPLETE + b"\x00" * 500)
    assert not _is_truncated(pdf)


def test_nul_padding_after_eof_is_intact(tmp_path):
    # Real scanners pad hundreds of KB of NULs after %%EOF; those PDFs are fine.
    pdf = _write(tmp_path / "a.pdf", COMPLETE + b"\x00" * 500_000)
    assert not _is_truncated(pdf)


def test_cut_off_pdf_is_truncated(tmp_path):
    # Mirrors the real failure: a scan cut off mid-stream, no %%EOF trailer.
    pdf = _write(tmp_path / "a.pdf", b"%PDF-1.7\n" + b"x" * 4096)
    assert _is_truncated(pdf)


def test_eof_buried_before_tail_is_truncated(tmp_path):
    # An incremental-update PDF cut off after the first %%EOF is still truncated.
    pdf = _write(tmp_path / "a.pdf", COMPLETE + b"x" * 4096)
    assert _is_truncated(pdf)


def test_non_pdf_is_never_truncated(tmp_path):
    assert not _is_truncated(_write(tmp_path / "a.jpg", b"\xff\xd8"))


def test_filter_intact_keeps_truncated_in_place(tmp_path):
    good = _write(tmp_path / "good.pdf", COMPLETE)
    bad = _write(tmp_path / "bad.pdf", b"%PDF-1.7\n")
    intact, truncated = _filter_intact([good, bad])
    assert intact == [good]
    assert truncated == 1
    assert bad.exists()


@patch("obagent.commands.consume._consume_path", return_value=(1, 0))
@patch("obagent.commands.consume.OpenAI")
@patch("obagent.commands.consume.Mistral")
def test_consume_all_fails_after_consuming_the_rest(
    mock_mistral, mock_openai, mock_consume, runner, vault, tmp_path
):
    """A truncated scan doesn't block its batch, but the pass exits non-zero."""
    for mock in (mock_mistral, mock_openai):
        mock.return_value.__enter__ = lambda self: self
        mock.return_value.__exit__ = lambda self, *args: False
    inbox = tmp_path / "inbox"
    good = _write(inbox / "Documents" / "good.pdf", COMPLETE)
    bad = _write(inbox / "Documents" / "bad.pdf", b"%PDF-1.7\n")

    result = runner.invoke(
        consume_all,
        [*BOTH_KEYS, "--input-dir", str(inbox), "--no-classify"],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 1, result.output
    # Count not pinned: other tests can register extra pipelines on the same dir.
    assert "truncated source file(s) left in the inbox" in result.output
    consumed = [s for c in mock_consume.call_args_list for s in c.args[2]]
    assert good in consumed and bad not in consumed
    assert bad.exists()
