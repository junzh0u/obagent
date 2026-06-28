import os
import time
from pathlib import Path

from commands.consume import _filter_stable


def test_filter_stable_skips_recent(tmp_path):
    old = tmp_path / "old.pdf"
    old.write_bytes(b"x")
    new = tmp_path / "new.pdf"
    new.write_bytes(b"y")
    past = time.time() - 120
    os.utime(old, (past, past))  # settled 2 min ago
    out = _filter_stable([old, new], 60)
    assert out == [old]  # new (just written) is still settling


def test_filter_stable_disabled_returns_all():
    paths = [Path("/a.pdf"), Path("/b.pdf")]
    assert _filter_stable(paths, 0) is paths  # min_age=0 -> no-op
