import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from commands.consume import consume


def _mock_ocr_response():
    """Create a mock OCR response with realistic structure."""
    page1 = SimpleNamespace(markdown="# Page 1\n\nHello world")
    page2 = SimpleNamespace(markdown="# Page 2\n\nGoodbye world")
    response = MagicMock()
    response.pages = [page1, page2]
    response.model_dump.return_value = {
        "pages": [
            {"markdown": "# Page 1\n\nHello world", "index": 0},
            {"markdown": "# Page 2\n\nGoodbye world", "index": 1},
        ],
        "model": "mistral-ocr-latest",
    }
    return response


def test_sha256_is_correct(runner, vault, source_dir):
    """The stored sha256 matches what hashlib computes."""
    content = b"hello world pdf content"
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()

    result = runner.invoke(
        consume,
        ["--path", "papers", str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    target_dir = vault / "papers" / expected_hash
    assert target_dir.exists()
    assert (target_dir / "original.pdf").read_bytes() == content
    meta = json.loads((target_dir / "metadata.json").read_text())
    assert meta["sha256"] == expected_hash


def test_metadata_structure(runner, vault, source_dir):
    """metadata.json contains all required fields with correct types."""
    pdf = source_dir / "test.pdf"
    pdf.write_bytes(b"metadata test")

    runner.invoke(
        consume,
        ["--path", "docs", str(source_dir)],
        obj={"vault": str(vault)},
    )

    meta_files = list(vault.rglob("metadata.json"))
    assert len(meta_files) == 1
    meta = json.loads(meta_files[0].read_text())
    assert set(meta.keys()) == {"original_filepath", "sha256", "consumed_at"}
    assert meta["original_filepath"].endswith("test.pdf")
    # consumed_at should be a valid ISO 8601 string
    from datetime import datetime

    datetime.fromisoformat(meta["consumed_at"])


def test_original_file_is_moved(runner, vault, source_dir):
    """The source PDF is removed after consuming."""
    pdf = source_dir / "move_me.pdf"
    pdf.write_bytes(b"will be moved")

    runner.invoke(
        consume,
        ["--path", "inbox", str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert not pdf.exists()
    originals = list(vault.rglob("original.pdf"))
    assert len(originals) == 1
    assert originals[0].read_bytes() == b"will be moved"


def test_duplicate_is_skipped(runner, vault, source_dir):
    """A PDF with the same hash as an existing entry is skipped."""
    content = b"duplicate content"
    sha256 = hashlib.sha256(content).hexdigest()

    # Pre-create the target directory to simulate a prior consume
    existing_dir = vault / "papers" / sha256
    existing_dir.mkdir(parents=True)
    (existing_dir / "original.pdf").write_bytes(content)

    pdf = source_dir / "dup.pdf"
    pdf.write_bytes(content)

    result = runner.invoke(
        consume,
        ["--path", "papers", str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert "Warning" in result.output
    assert "skipping" in result.output
    # Source file should NOT have been moved
    assert pdf.exists()


def test_no_pdfs_does_nothing(runner, vault, source_dir):
    """An empty source directory produces no output and no vault entries."""
    result = runner.invoke(
        consume,
        ["--path", "papers", str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert result.output == ""
    assert list(vault.iterdir()) == []


@patch("commands.consume.Mistral")
def test_ocr_results_saved_to_correct_paths(
    mock_mistral_cls, runner, vault, source_dir
):
    """OCR results are saved to ocr/ subdirectory with correct filenames."""
    mock_client = MagicMock()
    mock_client.ocr.process.return_value = _mock_ocr_response()
    mock_mistral_cls.return_value = mock_client

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"ocr test content")
    sha = hashlib.sha256(b"ocr test content").hexdigest()

    result = runner.invoke(
        consume,
        ["--path", "papers", "--mistral-api-key", "test-key", str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    ocr_dir = vault / "papers" / sha / "ocr"
    assert ocr_dir.exists()
    assert (ocr_dir / "mistral-ocr-latest.json").exists()
    assert (ocr_dir / "mistral-ocr-latest.txt").exists()


@patch("commands.consume.Mistral")
def test_ocr_text_contains_concatenated_markdown(
    mock_mistral_cls, runner, vault, source_dir
):
    """OCR text file contains page markdowns separated by double newlines."""
    mock_client = MagicMock()
    mock_client.ocr.process.return_value = _mock_ocr_response()
    mock_mistral_cls.return_value = mock_client

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"ocr text test")
    sha = hashlib.sha256(b"ocr text test").hexdigest()

    runner.invoke(
        consume,
        ["--path", "papers", "--mistral-api-key", "test-key", str(source_dir)],
        obj={"vault": str(vault)},
    )

    txt = (vault / "papers" / sha / "ocr" / "mistral-ocr-latest.txt").read_text()
    assert txt == "# Page 1\n\nHello world\n\n# Page 2\n\nGoodbye world"


@patch("commands.consume.Mistral")
def test_ocr_json_contains_model_dump(mock_mistral_cls, runner, vault, source_dir):
    """OCR JSON file contains valid JSON from model_dump()."""
    mock_client = MagicMock()
    mock_response = _mock_ocr_response()
    mock_client.ocr.process.return_value = mock_response
    mock_mistral_cls.return_value = mock_client

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"ocr json test")
    sha = hashlib.sha256(b"ocr json test").hexdigest()

    runner.invoke(
        consume,
        ["--path", "papers", "--mistral-api-key", "test-key", str(source_dir)],
        obj={"vault": str(vault)},
    )

    json_path = vault / "papers" / sha / "ocr" / "mistral-ocr-latest.json"
    data = json.loads(json_path.read_text())
    assert data == mock_response.model_dump.return_value
    assert data["model"] == "mistral-ocr-latest"
    assert len(data["pages"]) == 2


@patch("commands.consume.Mistral")
def test_no_ocr_without_api_key(mock_mistral_cls, runner, vault, source_dir):
    """OCR is skipped when no API key is provided."""
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"no ocr content")
    sha = hashlib.sha256(b"no ocr content").hexdigest()

    result = runner.invoke(
        consume,
        ["--path", "papers", str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert not (vault / "papers" / sha / "ocr").exists()
    mock_mistral_cls.assert_not_called()
