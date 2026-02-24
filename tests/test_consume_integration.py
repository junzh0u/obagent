import hashlib
import json
from unittest.mock import patch

from main import cli

from constants import LLM_MODEL, OCR_MODEL

from tests.conftest import BOTH_KEYS, setup_mock_mistral, setup_mock_openai


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_full_consume_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """End-to-end: invoke through the top-level CLI group."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "report.pdf"
    pdf.write_bytes(b"full integration test")
    expected_hash = hashlib.sha256(b"full integration test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "reports",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Ingested" in result.output

    target_dir = vault / "reports" / "_assets_" / expected_hash
    assert (target_dir / "src" / "original.pdf").exists()
    assert (target_dir / "src" / "metadata.json").exists()
    assert not pdf.exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_default_path_is_receipts(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Without --path, files are stored under 'Receipts'."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(b"default path test")
    sha = hashlib.sha256(b"default path test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert (vault / "Receipts" / "_assets_" / sha / "src" / "original.pdf").exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_consume_multiple_files(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Multiple files are each consumed into separate sha256 directories."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

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
            "receipt",
            "--path",
            "multi",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    for name, sha in files.items():
        target_dir = vault / "multi" / "_assets_" / sha
        assert (target_dir / "src" / "original.pdf").read_bytes() is not None
        meta = json.loads((target_dir / "src" / "metadata.json").read_text())
        assert meta["sha256"] == sha
        assert name in meta["original_filepath"]


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_consume_nested_files(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Files in subdirectories are found via rglob."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    sub = source_dir / "nested" / "deep"
    sub.mkdir(parents=True)
    pdf = sub / "deep.pdf"
    pdf.write_bytes(b"nested content")

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "nested",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Ingested" in result.output
    assert not pdf.exists()
    assert len(list((vault / "nested").iterdir())) == 2  # _assets_ dir + .md file


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_duplicate_skip_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Duplicate detection works through the full CLI."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    content = b"same content"
    pdf = source_dir / "first.pdf"
    pdf.write_bytes(content)

    # First consume
    runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "dup",
            "consume",
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
            "receipt",
            "--path",
            "dup",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Warning" in result.output
    assert "skipping" in result.output
    assert len(list((vault / "dup").iterdir())) == 2  # _assets_ dir + .md file


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_unsupported_files_are_ignored(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Only supported files are consumed; other files are left untouched."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    (source_dir / "notes.txt").write_text("not a pdf")
    (source_dir / "image.png").write_bytes(b"png data")
    pdf = source_dir / "real.pdf"
    pdf.write_bytes(b"pdf data")

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "mixed",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert (source_dir / "notes.txt").exists()
    assert (source_dir / "image.png").exists()
    assert not pdf.exists()
    assert len(list((vault / "mixed").iterdir())) == 2  # _assets_ dir + .md file


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_keep_original_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """--keep-original preserves source files through full CLI."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "keep.pdf"
    pdf.write_bytes(b"keep me via cli")

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "kept",
            "consume",
            "--keep-original",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Ingested" in result.output
    assert pdf.exists()


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_overwrite_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """--overwrite replaces existing entries through full CLI."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    content = b"overwrite via cli"
    sha = hashlib.sha256(content).hexdigest()

    # First consume
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)
    runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "ow",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    # Plant a stale .md to verify --overwrite cleans it up
    (vault / "ow" / "stale note.md").write_text("stale")

    # Re-create and consume again with --overwrite
    pdf.write_bytes(content)
    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "ow",
            "consume",
            "--overwrite",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Ingested" in result.output
    assert "Warning" not in result.output
    assert not (vault / "ow" / "stale note.md").exists()
    assert len(list((vault / "ow").iterdir())) == 2  # _assets_ dir + .md file
    assert (
        vault / "ow" / "_assets_" / sha / "src" / "original.pdf"
    ).read_bytes() == content


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_overwrite_re_ocrs_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """--overwrite forces re-OCR through full CLI."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    content = b"re-ocr via cli"
    sha = hashlib.sha256(content).hexdigest()

    # Pre-create target with old OCR
    target = vault / "reocr" / "_assets_" / sha
    ocr_dir = target / "ocr"
    ocr_dir.mkdir(parents=True)
    (target / "src").mkdir(parents=True)
    (target / "src" / "original.pdf").write_bytes(content)
    (ocr_dir / f"{OCR_MODEL}.txt").write_text("stale")

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "reocr",
            "consume",
            "--overwrite",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "OCR completed" in result.output
    txt = (ocr_dir / f"{OCR_MODEL}.txt").read_text()
    assert "stale" not in txt
    assert "# Page 1" in txt


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_via_cli_flag(mock_mistral_cls, mock_openai_cls, runner, vault, source_dir):
    """Full CLI with API key flags runs OCR end-to-end."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "report.pdf"
    pdf.write_bytes(b"cli ocr test")
    sha = hashlib.sha256(b"cli ocr test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "reports",
            "consume",
            "--mistral-api-key",
            "sk-test-key",
            "--openai-api-key",
            "ok-test-key",
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "OCR completed" in result.output
    ocr_dir = vault / "reports" / "_assets_" / sha / "ocr"
    assert (ocr_dir / f"{OCR_MODEL}.json").exists()
    assert (ocr_dir / f"{OCR_MODEL}.txt").exists()
    mock_mistral_cls.assert_any_call(api_key="sk-test-key")


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_via_env_var(mock_mistral_cls, mock_openai_cls, runner, vault, source_dir):
    """API keys from env vars are used."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "env.pdf"
    pdf.write_bytes(b"env var ocr test")
    sha = hashlib.sha256(b"env var ocr test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "envtest",
            "consume",
            str(source_dir),
        ],
        env={"MISTRAL_API_KEY": "sk-env-key", "OPENAI_API_KEY": "ok-env-key"},
    )

    assert result.exit_code == 0
    assert "OCR completed" in result.output
    ocr_dir = vault / "envtest" / "_assets_" / sha / "ocr"
    assert (ocr_dir / f"{OCR_MODEL}.json").exists()
    assert (ocr_dir / f"{OCR_MODEL}.txt").exists()
    mock_mistral_cls.assert_any_call(api_key="sk-env-key")


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_ocr_files_content_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Verify OCR file contents are correct through full CLI invocation."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    pdf = source_dir / "content.pdf"
    pdf.write_bytes(b"content check")
    sha = hashlib.sha256(b"content check").hexdigest()

    runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "check",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    ocr_dir = vault / "check" / "_assets_" / sha / "ocr"
    txt = (ocr_dir / f"{OCR_MODEL}.txt").read_text()
    assert "# Page 1" in txt
    assert "# Page 2" in txt
    assert "Hello world" in txt
    assert "Goodbye world" in txt

    data = json.loads((ocr_dir / f"{OCR_MODEL}.json").read_text())
    assert data["model"] == OCR_MODEL
    assert len(data["pages"]) == 2


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_title_md_created_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """Title markdown file is created with frontmatter through full CLI."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(
        mock_openai_cls, merchant="Bookstore", date="2024-09-20", total="$29.99"
    )

    pdf = source_dir / "paper.pdf"
    pdf.write_bytes(b"title cli test")
    sha = hashlib.sha256(b"title cli test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "papers",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    target_dir = vault / "papers" / "_assets_" / sha
    # LLM JSON created
    json_path = target_dir / "llm" / f"{LLM_MODEL}.json"
    assert json_path.exists()
    fields = json.loads(json_path.read_text())
    assert fields["merchant"] == "Bookstore"
    assert fields["date"] == "2024-09-20"
    assert fields["total"] == "$29.99"
    # Rendered markdown at vault/papers/ level
    assert "Title: 2024-09-20 - Bookstore - $29.99" in result.output
    md_file = vault / "papers" / "2024-09-20 - Bookstore - $29.99.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert 'merchant: "Bookstore"' in content
    assert 'date: "2024-09-20"' in content
    assert 'total: "$29.99"' in content
    assert f"![[_assets_/{sha}/src/original.pdf#height]]" in content


@patch("commands.consume.OpenAI")
@patch("commands.consume.Mistral")
def test_consume_jpeg_via_cli(
    mock_mistral_cls, mock_openai_cls, runner, vault, source_dir
):
    """End-to-end: JPEG file is consumed through the full CLI pipeline."""
    setup_mock_mistral(mock_mistral_cls)
    setup_mock_openai(mock_openai_cls)

    jpg = source_dir / "receipt.jpg"
    jpg.write_bytes(b"jpeg integration test")
    expected_hash = hashlib.sha256(b"jpeg integration test").hexdigest()

    result = runner.invoke(
        cli,
        [
            "--vault",
            str(vault),
            "receipt",
            "--path",
            "photos",
            "consume",
            *BOTH_KEYS,
            str(source_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Ingested" in result.output

    target_dir = vault / "photos" / "_assets_" / expected_hash
    assert (target_dir / "src" / "original.jpg").exists()
    assert not (target_dir / "src" / "original.pdf").exists()
    assert (target_dir / "src" / "metadata.json").exists()
    assert not jpg.exists()
