import hashlib
import json
from datetime import datetime

from commands.ingest import ingest


def test_sha256_is_correct(runner, vault, source_dir):
    """The stored sha256 matches what hashlib computes."""
    content = b"hello world pdf content"
    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()

    result = runner.invoke(
        ingest,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    target_dir = vault / "papers" / "_assets_" / expected_hash
    assert target_dir.exists()
    assert (target_dir / "src" / "original.pdf").read_bytes() == content
    meta = json.loads((target_dir / "src" / "metadata.json").read_text())
    assert meta["sha256"] == expected_hash


def test_metadata_structure(runner, vault, source_dir):
    """metadata.json contains all required fields with correct types."""
    pdf = source_dir / "test.pdf"
    pdf.write_bytes(b"metadata test")

    runner.invoke(
        ingest,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "docs"},
    )

    meta_files = list(vault.rglob("metadata.json"))
    assert len(meta_files) == 1
    meta = json.loads(meta_files[0].read_text())
    assert set(meta.keys()) == {"original_filepath", "sha256", "consumed_at"}
    assert meta["original_filepath"].endswith("test.pdf")
    datetime.fromisoformat(meta["consumed_at"])


def test_original_file_is_moved(runner, vault, source_dir):
    """The source PDF is removed after ingesting."""
    pdf = source_dir / "move_me.pdf"
    pdf.write_bytes(b"will be moved")

    runner.invoke(
        ingest,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "inbox"},
    )

    assert not pdf.exists()
    originals = list(vault.rglob("original.pdf"))
    assert len(originals) == 1
    assert originals[0].read_bytes() == b"will be moved"


def test_duplicate_is_skipped(runner, vault, source_dir):
    """A PDF with the same hash as an existing entry is skipped."""
    content = b"duplicate content"
    sha256 = hashlib.sha256(content).hexdigest()

    existing_dir = vault / "papers" / "_assets_" / sha256
    (existing_dir / "src").mkdir(parents=True)
    (existing_dir / "src" / "original.pdf").write_bytes(content)

    pdf = source_dir / "dup.pdf"
    pdf.write_bytes(content)

    result = runner.invoke(
        ingest,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Warning" in result.output
    assert "skipping" in result.output
    assert pdf.exists()


def test_no_pdfs_does_nothing(runner, vault, source_dir):
    """An empty source directory produces no output and no vault entries."""
    result = runner.invoke(
        ingest,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert result.output == ""
    assert list(vault.iterdir()) == []


def test_keep_original_preserves_source(runner, vault, source_dir):
    """With --keep-original, the source PDF remains after ingesting."""
    pdf = source_dir / "keep_me.pdf"
    pdf.write_bytes(b"copy me")

    result = runner.invoke(
        ingest,
        ["--keep-original", str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert pdf.exists()
    originals = list(vault.rglob("original.pdf"))
    assert len(originals) == 1
    assert originals[0].read_bytes() == b"copy me"


def test_overwrite_replaces_existing_entry(runner, vault, source_dir):
    """With --overwrite, an existing entry is replaced instead of skipped."""
    content = b"overwrite content"
    sha = hashlib.sha256(content).hexdigest()

    existing_dir = vault / "papers" / "_assets_" / sha
    (existing_dir / "src").mkdir(parents=True)
    (existing_dir / "src" / "original.pdf").write_bytes(b"old content")
    (existing_dir / "src" / "metadata.json").write_text('{"old": true}')

    pdf = source_dir / "new.pdf"
    pdf.write_bytes(content)

    result = runner.invoke(
        ingest,
        ["--overwrite", str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Warning" not in result.output
    assert "Consumed" in result.output
    assert (existing_dir / "src" / "original.pdf").read_bytes() == content
    meta = json.loads((existing_dir / "src" / "metadata.json").read_text())
    assert "old" not in meta
    assert meta["sha256"] == sha


def test_overwrite_without_existing_works_normally(runner, vault, source_dir):
    """--overwrite on a fresh ingest works the same as without it."""
    pdf = source_dir / "fresh.pdf"
    pdf.write_bytes(b"fresh content")
    sha = hashlib.sha256(b"fresh content").hexdigest()

    result = runner.invoke(
        ingest,
        ["--overwrite", str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "Consumed" in result.output
    assert (vault / "papers" / "_assets_" / sha / "src" / "original.pdf").exists()


def test_keep_original_and_overwrite_together(runner, vault, source_dir):
    """--keep-original and --overwrite can be used together."""
    content = b"both flags"
    sha = hashlib.sha256(content).hexdigest()

    existing_dir = vault / "papers" / "_assets_" / sha
    (existing_dir / "src").mkdir(parents=True)
    (existing_dir / "src" / "original.pdf").write_bytes(b"old")

    pdf = source_dir / "doc.pdf"
    pdf.write_bytes(content)

    result = runner.invoke(
        ingest,
        ["--keep-original", "--overwrite", str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert pdf.exists()
    assert (existing_dir / "src" / "original.pdf").read_bytes() == content


def test_non_pdf_files_are_ignored(runner, vault, source_dir):
    """Only .pdf files are ingested; other files are left untouched."""
    (source_dir / "notes.txt").write_text("not a pdf")
    (source_dir / "image.png").write_bytes(b"png data")
    pdf = source_dir / "real.pdf"
    pdf.write_bytes(b"pdf data")

    result = runner.invoke(
        ingest,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "mixed"},
    )

    assert result.exit_code == 0
    assert (source_dir / "notes.txt").exists()
    assert (source_dir / "image.png").exists()
    assert not pdf.exists()
    assert len(list((vault / "mixed").iterdir())) == 1
