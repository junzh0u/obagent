def newest_file(directory, glob_pattern):
    """Return the newest file (by mtime) matching glob_pattern in directory, or None."""
    newest = None
    for p in directory.glob(glob_pattern) if directory.exists() else ():
        if newest is None or p.stat().st_mtime > newest.stat().st_mtime:
            newest = p
    return newest
