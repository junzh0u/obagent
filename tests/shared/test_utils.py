import os

from utils import newest_file, pinyin_sort_key, source_file


def test_nonexistent_dir(tmp_path):
    assert newest_file(tmp_path / "no_such_dir", "*.txt") is None


def test_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert newest_file(d, "*.txt") is None


def test_single_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    assert newest_file(tmp_path, "*.txt") == f


def test_returns_newest_by_mtime(tmp_path):
    old = tmp_path / "old.txt"
    old.write_text("old")
    # Ensure a measurable mtime difference
    old_mtime = old.stat().st_mtime
    os.utime(old, (old_mtime - 2, old_mtime - 2))

    new = tmp_path / "new.txt"
    new.write_text("new")

    assert newest_file(tmp_path, "*.txt") == new


def test_glob_pattern_filters(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("text")
    json_f = tmp_path / "b.json"
    json_f.write_text("{}")

    assert newest_file(tmp_path, "*.txt") == txt
    assert newest_file(tmp_path, "*.json") == json_f


def test_source_file_finds_pdf(tmp_path):
    """source_file returns original.pdf when present."""
    target_dir = tmp_path / "entry"
    src_dir = target_dir / "src"
    src_dir.mkdir(parents=True)
    pdf = src_dir / "original.pdf"
    pdf.write_bytes(b"pdf data")
    assert source_file(target_dir) == pdf


def test_source_file_finds_jpg(tmp_path):
    """source_file returns original.jpg when present."""
    target_dir = tmp_path / "entry"
    src_dir = target_dir / "src"
    src_dir.mkdir(parents=True)
    jpg = src_dir / "original.jpg"
    jpg.write_bytes(b"jpg data")
    assert source_file(target_dir) == jpg


def test_source_file_returns_none(tmp_path):
    """source_file returns None when no original.* exists."""
    target_dir = tmp_path / "entry"
    src_dir = target_dir / "src"
    src_dir.mkdir(parents=True)
    assert source_file(target_dir) is None


def test_pinyin_sort_key_chinese_names():
    """Chinese names sort by pinyin, not Unicode code point."""
    names = ["周俊", "张伟", "李明"]
    assert sorted(names, key=pinyin_sort_key) == ["李明", "张伟", "周俊"]


def test_pinyin_sort_key_ascii_before_cjk():
    """ASCII names always sort before CJK names, even with overlapping pinyin."""
    names = ["周俊", "Alice", "艾伟", "Bob"]
    assert sorted(names, key=pinyin_sort_key) == ["Alice", "Bob", "艾伟", "周俊"]
