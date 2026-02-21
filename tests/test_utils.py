import os
import time

from utils import newest_file


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
