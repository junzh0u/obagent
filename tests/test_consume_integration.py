import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from main import cli

BOTH_KEYS = ["--mistral-api-key", "mk-test", "--openai-api-key", "ok-test"]


def _mock_ocr_response():
    """Create a mock OCR response with realistic structure."""
    page1 = SimpleNamespace(markdown="# Page 1\n\nContent A")
    page2 = SimpleNamespace(markdown="# Page 2\n\nContent B")
    response = MagicMock()
    response.pages = [page1, page2]
    response.model_dump.return_value = {
        "pages": [
            {"markdown": "# Page 1\n\nContent A", "index": 0},
            {"markdown": "# Page 2\n\nContent B", "index": 1},
        ],
        "model": "mistral-ocr-latest",
    }
    return response


def _mock_chat_response(title="My Document Title"):
    """Create a mock OpenAI chat completion response for title extraction."""
    message = SimpleNamespace(content=title)
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


def _setup_mock_openai(mock_openai_cls, title="My Document Title"):
    """Set up a mock OpenAI client with chat response."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_chat_response(title)
    mock_openai_cls.return_value = mock_client
    return mock_client


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_full_consume_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """End-to-end: invoke through the top-level CLI group."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "report.pdf"
    pdf.write_bytes(b"full integration test")
    expected_hash = hashlib.sha256(b"full integration test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "reports",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Consumed" in result.output

    target_dir = vault / "reports" / expected_hash
    assert (target_dir / "original.pdf").exists()
    assert (target_dir / "metadata.json").exists()
    assert not pdf.exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_consume_multiple_pdfs(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Multiple PDFs are each consumed into separate sha256 directories."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    files = {}
    for name, content in [("a.pdf", b"aaa"), ("b.pdf", b"bbb"), ("c.pdf", b"ccc")]:
        pdf = source_dir / name
        pdf.write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "multi",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    for name, sha in files.items():
        target_dir = vault / "multi" / sha
        assert (target_dir / "original.pdf").read_bytes() is not None
        meta = json.loads((target_dir / "metadata.json").read_text())
        assert meta["sha256"] == sha
        assert name in meta["original_filepath"]


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_consume_nested_pdfs(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """PDFs in subdirectories are found via rglob."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    sub = source_dir / "nested" / "deep"
    sub.mkdir(parents=True)
    pdf = sub / "deep.pdf"
    pdf.write_bytes(b"nested content")

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "nested",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Consumed" in result.output
    assert not pdf.exists()
    assert len(list((vault / "nested").iterdir())) == 1


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_duplicate_skip_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Duplicate detection works through the full CLI."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    content = b"same content"
    pdf = source_dir / "first.pdf"
    pdf.write_bytes(content)

    # First consume
    runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "dup",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    # Re-create the same file
    pdf.write_bytes(content)

    # Second consume — should skip
    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "dup",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Warning" in result.output
    assert "skipping" in result.output
    # Only one entry in the vault
    assert len(list((vault / "dup").iterdir())) == 1


def test_path_option_is_required(runner, vault, source_dir):
    """Omitting --path results in an error."""
    result = runner.invoke(
        cli,
        ["--vault", str(vault), "consume", str(source_dir)],
    )

    assert result.exit_code != 0
    assert "Missing option" in result.output or "--path" in result.output


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_non_pdf_files_are_ignored(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Only .pdf files are consumed; other files are left untouched."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    (source_dir / "notes.txt").write_text("not a pdf")
    (source_dir / "image.png").write_bytes(b"png data")
    pdf = source_dir / "real.pdf"
    pdf.write_bytes(b"pdf data")

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "mixed",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert (source_dir / "notes.txt").exists()
    assert (source_dir / "image.png").exists()
    assert not pdf.exists()
    assert len(list((vault / "mixed").iterdir())) == 1


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_keep_original_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """--keep-original preserves source PDFs through full CLI."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "keep.pdf"
    pdf.write_bytes(b"keep me via cli")

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "kept",
            "--keep-original",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Consumed" in result.output
    assert pdf.exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_overwrite_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """--overwrite replaces existing entries through full CLI."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    content = b"overwrite via cli"
    sha = hashlib.sha256(content).hexdigest()

    # First consume
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)
    runner.invoke(
        cli,
        ["--vault", str(vault), "consume", "--path", "ow", *BOTH_KEYS, str(source_dir)],
    )

    # Re-create and consume again with --overwrite
    pdf.write_bytes(content)
    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "ow",
            "--overwrite",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Consumed" in result.output
    assert "Warning" not in result.output
    assert len(list((vault / "ow").iterdir())) == 1
    assert (vault / "ow" / sha / "original.pdf").read_bytes() == content


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_overwrite_re_ocrs_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """--overwrite forces re-OCR through full CLI."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    content = b"re-ocr via cli"
    sha = hashlib.sha256(content).hexdigest()

    # Pre-create target with old OCR
    target = vault / "reocr" / sha
    ocr_dir = target / "ocr"
    ocr_dir.mkdir(parents=True)
    (target / "original.pdf").write_bytes(content)
    (ocr_dir / "mistral-ocr-latest.txt").write_text("stale")

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "reocr",
            "--overwrite",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "OCR completed" in result.output
    txt = (ocr_dir / "mistral-ocr-latest.txt").read_text()
    assert "stale" not in txt
    assert "# Page 1" in txt


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_via_cli_flag(mock_mistral_cls, mock_openai_cls, runner, vault, source_dir):
    """Full CLI with API key flags runs OCR end-to-end."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "report.pdf"
    pdf.write_bytes(b"cli ocr test")
    sha = hashlib.sha256(b"cli ocr test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "reports",
            "--mistral-api-key",
            "sk-test-key",
            "--openai-api-key",
            "ok-test-key",
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "OCR completed" in result.output
    ocr_dir = vault / "reports" / sha / "ocr"
    assert (ocr_dir / "mistral-ocr-latest.json").exists()
    assert (ocr_dir / "mistral-ocr-latest.txt").exists()
    mock_mistral_cls.assert_any_call(api_key="sk-test-key")


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_via_env_var(mock_mistral_cls, mock_openai_cls, runner, vault, source_dir):
    """API keys from env vars are used."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "env.pdf"
    pdf.write_bytes(b"env var ocr test")
    sha = hashlib.sha256(b"env var ocr test").hexdigest()

    result = runner.invoke(
        cli,
        ["--vault", str(vault), "consume", "--path", "envtest", str(source_dir)],
        env={"MISTRAL_API_KEY": "sk-env-key", "OPENAI_API_KEY": "ok-env-key"},
    )

    assert result.exit_code == 0
    assert "OCR completed" in result.output
    ocr_dir = vault / "envtest" / sha / "ocr"
    assert (ocr_dir / "mistral-ocr-latest.json").exists()
    assert (ocr_dir / "mistral-ocr-latest.txt").exists()
    mock_mistral_cls.assert_any_call(api_key="sk-env-key")


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_files_content_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Verify OCR file contents are correct through full CLI invocation."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "content.pdf"
    pdf.write_bytes(b"content check")
    sha = hashlib.sha256(b"content check").hexdigest()

    runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "check",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    ocr_dir = vault / "check" / sha / "ocr"
    txt = (ocr_dir / "mistral-ocr-latest.txt").read_text()
    assert "# Page 1" in txt
    assert "# Page 2" in txt
    assert "Content A" in txt
    assert "Content B" in txt

    data = json.loads((ocr_dir / "mistral-ocr-latest.json").read_text())
    assert data["model"] == "mistral-ocr-latest"
    assert len(data["pages"]) == 2


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_title_md_created_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Title markdown file is created through full CLI invocation."""
    _setup_mock_mistral(mock_mistral_cls)
    _setup_mock_openai(mock_openai_cls, title="Deep Learning Survey")

    pdf = source_dir / "paper.pdf"
    pdf.write_bytes(b"title cli test")
    sha = hashlib.sha256(b"title cli test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "consume",
            "--path",
            "papers",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Title: Deep Learning Survey" in result.output
    md_file = vault / "papers" / sha / "Deep Learning Survey.md"
    assert md_file.exists()
    assert md_file.read_text() == "![[original.pdf]]\n"
