import signal

import click

from constants import ASSETS_DIR


def interruptible(iterable):
    """Yield items, allowing graceful Ctrl+C between iterations.

    First Ctrl+C: finish current item, stop before next.
    Second Ctrl+C: force quit immediately.
    """
    stop = False
    original = signal.getsignal(signal.SIGINT)

    def handler(signum, frame):
        nonlocal stop
        if stop:
            signal.signal(signal.SIGINT, original)
            raise KeyboardInterrupt
        stop = True
        click.secho(
            "\nInterrupted — finishing current item. Ctrl+C again to force quit.",
            fg="yellow",
        )

    signal.signal(signal.SIGINT, handler)
    try:
        for item in iterable:
            yield item
            if stop:
                click.secho("Stopped.", fg="yellow")
                break
    finally:
        signal.signal(signal.SIGINT, original)


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


def source_file(target_dir):
    """Return the original.* source file under target_dir/src/, or None."""
    for p in (target_dir / "src").glob("original.*"):
        if p.is_file():
            return p
    return None
