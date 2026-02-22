from constants import ASSETS_DIR


def iter_entries(vault, path):
    """Yield sorted sha256 target dirs under vault/path/_assets_/."""
    assets_dir = vault / path / ASSETS_DIR
    if assets_dir.is_dir():
        yield from sorted(p for p in assets_dir.iterdir() if p.is_dir())


def newest_file(directory, glob_pattern):
    """Return the newest file (by mtime) matching glob_pattern in directory, or None."""
    newest = None
    for p in directory.glob(glob_pattern) if directory.exists() else ():
        if newest is None or p.stat().st_mtime > newest.stat().st_mtime:
            newest = p
    return newest


def make_safe_title(merchant, date, total):
    """Build a filesystem-safe title from receipt metadata fields."""
    total = total or "$0.00"
    parts = [p for p in (date, merchant, total) if p]
    title = " - ".join(parts)
    return "".join(c for c in title if c not in r'\/:*?"<>|').strip()
