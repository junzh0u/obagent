import hashlib
import json

from main import cli


def test_full_consume_via_cli(runner, vault, source_dir):
    """End-to-end: invoke through the top-level CLI group."""
    pdf = source_dir / "report.pdf"
    pdf.write_bytes(b"full integration test")
    expected_hash = hashlib.sha256(b"full integration test").hexdigest()

    result = runner.invoke(
        cli,
        ["--vault", str(vault), "consume", "--path", "reports", str(source_dir)],
    )

    assert result.exit_code == 0
    assert "Consumed" in result.output

    target_dir = vault / "reports" / expected_hash
    assert (target_dir / "original.pdf").exists()
    assert (target_dir / "metadata.json").exists()
    assert not pdf.exists()


def test_consume_multiple_pdfs(runner, vault, source_dir):
    """Multiple PDFs are each consumed into separate sha256 directories."""
    files = {}
    for name, content in [("a.pdf", b"aaa"), ("b.pdf", b"bbb"), ("c.pdf", b"ccc")]:
        pdf = source_dir / name
        pdf.write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()

    result = runner.invoke(
        cli,
        ["--vault", str(vault), "consume", "--path", "multi", str(source_dir)],
    )

    assert result.exit_code == 0
    for name, sha in files.items():
        target_dir = vault / "multi" / sha
        assert (target_dir / "original.pdf").read_bytes() is not None
        meta = json.loads((target_dir / "metadata.json").read_text())
        assert meta["sha256"] == sha
        assert name in meta["original_filepath"]


def test_consume_nested_pdfs(runner, vault, source_dir):
    """PDFs in subdirectories are found via rglob."""
    sub = source_dir / "nested" / "deep"
    sub.mkdir(parents=True)
    pdf = sub / "deep.pdf"
    pdf.write_bytes(b"nested content")

    result = runner.invoke(
        cli,
        ["--vault", str(vault), "consume", "--path", "nested", str(source_dir)],
    )

    assert result.exit_code == 0
    assert "Consumed" in result.output
    assert not pdf.exists()
    assert len(list((vault / "nested").iterdir())) == 1


def test_duplicate_skip_via_cli(runner, vault, source_dir):
    """Duplicate detection works through the full CLI."""
    content = b"same content"
    pdf = source_dir / "first.pdf"
    pdf.write_bytes(content)

    # First consume
    runner.invoke(
        cli,
        ["--vault", str(vault), "consume", "--path", "dup", str(source_dir)],
    )

    # Re-create the same file
    pdf.write_bytes(content)

    # Second consume — should skip
    result = runner.invoke(
        cli,
        ["--vault", str(vault), "consume", "--path", "dup", str(source_dir)],
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


def test_non_pdf_files_are_ignored(runner, vault, source_dir):
    """Only .pdf files are consumed; other files are left untouched."""
    (source_dir / "notes.txt").write_text("not a pdf")
    (source_dir / "image.png").write_bytes(b"png data")
    pdf = source_dir / "real.pdf"
    pdf.write_bytes(b"pdf data")

    result = runner.invoke(
        cli,
        ["--vault", str(vault), "consume", "--path", "mixed", str(source_dir)],
    )

    assert result.exit_code == 0
    assert (source_dir / "notes.txt").exists()
    assert (source_dir / "image.png").exists()
    assert not pdf.exists()
    assert len(list((vault / "mixed").iterdir())) == 1
