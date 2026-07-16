import re
import signal
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TypeVar

import click
from pypinyin import lazy_pinyin

from lib.constants import ASSETS_DIR

T = TypeVar("T")

SHA_RE = re.compile(r"_assets_/([^/]+)/src/")


def interruptible(iterable: Iterable[T]) -> Iterator[T]:
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


def iter_entries(vault: Path, path: str) -> Iterator[Path]:
    """Yield sorted sha256 target dirs under vault/path/_assets_/."""
    assets_dir = vault / path / ASSETS_DIR
    if assets_dir.is_dir():
        yield from sorted(p for p in assets_dir.iterdir() if p.is_dir())


def target_shas(path_dir: Path, target: str) -> list[str]:
    """Resolve a CLI entry target to sha256 ids.

    A target naming a note — an existing ``.md`` given as a path, or as a bare
    filename inside ``path_dir`` — yields the note's embedded shas in embed
    order (deduped); anything else is returned as-is, assumed to be a sha.
    Raises for a ``.md`` target that doesn't exist or embeds no assets.
    """
    md = next(
        (
            p
            for p in (Path(target), path_dir / target)
            if p.suffix == ".md" and p.is_file()
        ),
        None,
    )
    if md is None:
        if target.endswith(".md"):
            raise click.UsageError(f"Note not found: {target}")
        return [target]
    shas = list(dict.fromkeys(SHA_RE.findall(md.read_text())))
    if not shas:
        raise click.UsageError(f"No asset embeds found in {md.name}")
    return shas


def newest_file(directory: Path, glob_pattern: str) -> Path | None:
    """Return the newest file (by mtime) matching glob_pattern in directory, or None."""
    newest = None
    for p in directory.glob(glob_pattern) if directory.exists() else ():
        if newest is None or p.stat().st_mtime > newest.stat().st_mtime:
            newest = p
    return newest


def _has_cjk(s: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in s)


def pinyin_sort_key(s: str) -> tuple[int, list[str]]:
    """Sort key: ASCII names first, then CJK names by pinyin."""
    return (1 if _has_cjk(s) else 0, [part.lower() for part in lazy_pinyin(s)])


def source_file(target_dir: Path) -> Path | None:
    """Return the original.* source file under target_dir/src/, or None."""
    for p in (target_dir / "src").glob("original.*"):
        if p.is_file():
            return p
    return None
