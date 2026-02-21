import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from commands.consume import consume

BOTH_KEYS = ["--mistral-api-key", "test-key", "--openai-api-key", "test-oai-key"]


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


def _mock_chat_response(merchant="ACME Store", date="2024-01-15", total="$42.50"):
    """Create a mock OpenAI chat completion response for metadata extraction."""
    content = json.dumps({"merchant": merchant, "date": date, "total": total})
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def _setup_mock_mistral(mock_mistral_cls):
    """Set up a mock Mistral client with OCR response."""
    mock_client = MagicMock()
    mock_client.ocr.process.return_value = _mock_ocr_response()
    mock_mistral_cls.return_value = mock_client
    return mock_client


def _setup_mock_openai(mock_openai_cls, **kwargs):
    """Set up a mock OpenAI client with chat response."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_chat_response(**kwargs)
    mock_openai_cls.return_value = mock_client
    return mock_client


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_sha256_is_correct(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """The stored sha256 matches what hashlib computes."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    content = b"hello world pdf content"
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()

    result = runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    target_dir = vault / "papers" / expected_hash
    assert target_dir.exists()
    assert (target_dir / "original.pdf").read_bytes() == content
    meta = json.loads((target_dir / "metadata.json").read_text())
    assert meta["sha256"] == expected_hash


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_metadata_structure(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """metadata.json contains all required fields with correct types."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "test.pdf"
    pdf.write_bytes(b"metadata test")

    runner.invoke(
        consume,
        ["--path", "docs", *BOTH_KEYS, str(source_dir)],
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


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_original_file_is_moved(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """The source PDF is removed after consuming."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "move_me.pdf"
    pdf.write_bytes(b"will be moved")

    runner.invoke(
        consume,
        ["--path", "inbox", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert not pdf.exists()
    originals = list(vault.rglob("original.pdf"))
    assert len(originals) == 1
    assert originals[0].read_bytes() == b"will be moved"


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_duplicate_is_skipped(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """A PDF with the same hash as an existing entry is skipped."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

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
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert "Warning" in result.output
    assert "skipping" in result.output
    # Source file should NOT have been moved
    assert pdf.exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_no_pdfs_does_nothing(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """An empty source directory produces no output and no vault entries."""
    result = runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert result.output == ""
    assert list(vault.iterdir()) == []


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_keep_original_preserves_source(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """With --keep-original, the source PDF remains after consuming."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "keep_me.pdf"
    pdf.write_bytes(b"copy me")

    result = runner.invoke(
        consume,
        ["--path", "papers", "--keep-original", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert pdf.exists()
    originals = list(vault.rglob("original.pdf"))
    assert len(originals) == 1
    assert originals[0].read_bytes() == b"copy me"


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_overwrite_replaces_existing_entry(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """With --overwrite, an existing entry is replaced instead of skipped."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    content = b"overwrite content"
    sha = hashlib.sha256(content).hexdigest()

    # Pre-create the target directory with old data
    existing_dir = vault / "papers" / sha
    existing_dir.mkdir(parents=True)
    (existing_dir / "original.pdf").write_bytes(b"old content")
    (existing_dir / "metadata.json").write_text('{"old": true}')

    pdf = source_dir / "new.pdf"
    pdf.write_bytes(content)

    result = runner.invoke(
        consume,
        ["--path", "papers", "--overwrite", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert "Warning" not in result.output
    assert "Consumed" in result.output
    # PDF content should be the new content
    assert (existing_dir / "original.pdf").read_bytes() == content
    # Metadata should be refreshed
    meta = json.loads((existing_dir / "metadata.json").read_text())
    assert "old" not in meta
    assert meta["sha256"] == sha


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_overwrite_without_existing_works_normally(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """--overwrite on a fresh consume works the same as without it."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "fresh.pdf"
    pdf.write_bytes(b"fresh content")
    sha = hashlib.sha256(b"fresh content").hexdigest()

    result = runner.invoke(
        consume,
        ["--path", "papers", "--overwrite", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert "Consumed" in result.output
    assert (vault / "papers" / sha / "original.pdf").exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_overwrite_forces_re_ocr(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """With --overwrite, OCR is re-run even if ocr/ already exists."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    content = b"re-ocr content"
    sha = hashlib.sha256(content).hexdigest()

    # Pre-create target with old OCR data
    existing_dir = vault / "papers" / sha
    ocr_dir = existing_dir / "ocr"
    ocr_dir.mkdir(parents=True)
    (existing_dir / "original.pdf").write_bytes(content)
    (ocr_dir / "mistral-ocr-latest.txt").write_text("old ocr text")
    (ocr_dir / "mistral-ocr-latest.json").write_text('{"old": true}')

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)

    result = runner.invoke(
        consume,
        ["--path", "papers", "--overwrite", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    assert "OCR completed" in result.output
    # OCR files should contain new data, not old
    txt = (ocr_dir / "mistral-ocr-latest.txt").read_text()
    assert "old ocr text" not in txt
    assert "# Page 1" in txt
    data = json.loads((ocr_dir / "mistral-ocr-latest.json").read_text())
    assert "old" not in data


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_keep_original_and_overwrite_together(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """--keep-original and --overwrite can be used together."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    content = b"both flags"
    sha = hashlib.sha256(content).hexdigest()

    # Pre-create target
    existing_dir = vault / "papers" / sha
    existing_dir.mkdir(parents=True)
    (existing_dir / "original.pdf").write_bytes(b"old")

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)

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
    assert pdf.exists()  # --keep-original: source preserved
    assert (
        existing_dir / "original.pdf"
    ).read_bytes() == content  # --overwrite: replaced


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_results_saved_to_correct_paths(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """OCR results are saved to ocr/ subdirectory with correct filenames."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"ocr test content")
    sha = hashlib.sha256(b"ocr test content").hexdigest()

    result = runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    ocr_dir = vault / "papers" / sha / "ocr"
    assert ocr_dir.exists()
    assert (ocr_dir / "mistral-ocr-latest.json").exists()
    assert (ocr_dir / "mistral-ocr-latest.txt").exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_text_contains_concatenated_markdown(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """OCR text file contains page markdowns separated by double newlines."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"ocr text test")
    sha = hashlib.sha256(b"ocr text test").hexdigest()

    runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    txt = (vault / "papers" / sha / "ocr" / "mistral-ocr-latest.txt").read_text()
    assert txt == "# Page 1\n\nHello world\n\n# Page 2\n\nGoodbye world"


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_json_contains_model_dump(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """OCR JSON file contains valid JSON from model_dump()."""
    mock_client = _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)
    mock_response = mock_client.ocr.process.return_value

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"ocr json test")
    sha = hashlib.sha256(b"ocr json test").hexdigest()

    runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    json_path = vault / "papers" / sha / "ocr" / "mistral-ocr-latest.json"
    data = json.loads(json_path.read_text())
    assert data == mock_response.model_dump.return_value
    assert data["model"] == "mistral-ocr-latest"
    assert len(data["pages"]) == 2


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_title_md_created_after_ocr(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """A <title>.md file is created with frontmatter and Obsidian embed link."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(
        mock_openai_cls, merchant="Coffee Shop", date="2024-06-01", total="$5.75"
    )

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"title test")
    sha = hashlib.sha256(b"title test").hexdigest()

    result = runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    assert result.exit_code == 0
    target_dir = vault / "papers" / sha
    md_file = target_dir / "2024-06-01 - Coffee Shop - $5.75.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert 'merchant: "Coffee Shop"' in content
    assert 'date: "2024-06-01"' in content
    assert 'total: "$5.75"' in content
    assert "![[original.pdf]]" in content
    assert "Title: 2024-06-01 - Coffee Shop - $5.75" in result.output


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_title_sanitizes_unsafe_characters(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Unsafe filename characters are stripped from the title."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(
        mock_openai_cls, merchant='Shop "A"/B', date="2024-01-15", total="$10.00"
    )

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"sanitize test")
    sha = hashlib.sha256(b"sanitize test").hexdigest()

    runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    target_dir = vault / "papers" / sha
    md_file = target_dir / "2024-01-15 - Shop AB - $10.00.md"
    assert md_file.exists()
    assert "![[original.pdf]]" in md_file.read_text()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_title_uses_openai_gpt5_mini(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Metadata extraction calls OpenAI gpt-5-mini with OCR text."""
    _setup_mock_mistral(mock_mistral_cls)
    mock_openai_client = _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"chat model test")

    runner.invoke(
        consume,
        ["--path", "papers", *BOTH_KEYS, str(source_dir)],
        obj={"vault": str(vault)},
    )

    mock_openai_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_openai_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "gpt-5-mini"
    prompt = call_kwargs.kwargs["messages"][0]["content"]
    assert "partially read by OCR" in prompt
    assert '"papers"' in prompt
    assert "merchant" in prompt
    assert "date" in prompt
    assert "total" in prompt
    assert "JSON" in prompt
    assert "# Page 1" in prompt
