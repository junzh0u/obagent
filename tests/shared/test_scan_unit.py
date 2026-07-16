import hashlib

from commands.scan import scan


def test_scan_shows_new_files(runner, vault, source_dir):
    """Scan reports new files that aren't in the vault."""
    pdf = source_dir / "new.pdf"
    pdf.write_bytes(b"new content")

    result = runner.invoke(
        scan,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "new.pdf" in result.output
    assert "new" in result.output
    assert "1 files found: 1 new, 0 already consumed" in result.output


def test_scan_shows_duplicates(runner, vault, source_dir):
    """Scan reports files that already exist in the vault."""
    content = b"duplicate content"
    sha256 = hashlib.sha256(content).hexdigest()

    existing_dir = vault / "papers" / "_assets_" / sha256
    (existing_dir / "src").mkdir(parents=True)
    (existing_dir / "src" / "original.pdf").write_bytes(content)

    pdf = source_dir / "dup.pdf"
    pdf.write_bytes(content)

    result = runner.invoke(
        scan,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "dup.pdf" in result.output
    assert "duplicate" in result.output
    assert "1 files found: 0 new, 1 already consumed" in result.output


def test_scan_mixed(runner, vault, source_dir):
    """Scan correctly counts a mix of new and duplicate files."""
    dup_content = b"existing"
    sha256 = hashlib.sha256(dup_content).hexdigest()
    existing_dir = vault / "papers" / "_assets_" / sha256
    (existing_dir / "src").mkdir(parents=True)

    (source_dir / "dup.pdf").write_bytes(dup_content)
    (source_dir / "new1.pdf").write_bytes(b"brand new 1")
    (source_dir / "new2.pdf").write_bytes(b"brand new 2")

    result = runner.invoke(
        scan,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "3 files found: 2 new, 1 already consumed" in result.output


def test_scan_no_side_effects(runner, vault, source_dir):
    """Scan does not create vault entries or move source files."""
    pdf = source_dir / "stay.pdf"
    pdf.write_bytes(b"stay here")

    result = runner.invoke(
        scan,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert pdf.exists(), "source PDF should not be moved"
    assert not [p for p in vault.iterdir() if p.name != ".obagent"], (
        "vault should remain empty"
    )


def test_scan_empty_dir(runner, vault, source_dir):
    """Scan on an empty directory reports zero files."""
    result = runner.invoke(
        scan,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "0 files found: 0 new, 0 already consumed" in result.output


def test_scan_jpeg(runner, vault, source_dir):
    """Scan detects JPEG files as new."""
    jpg = source_dir / "photo.jpg"
    jpg.write_bytes(b"jpeg scan test")

    result = runner.invoke(
        scan,
        [str(source_dir)],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "photo.jpg" in result.output
    assert "new" in result.output
    assert "1 files found: 1 new, 0 already consumed" in result.output
