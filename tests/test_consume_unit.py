import hashlib
import json

from commands.consume import consume


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
