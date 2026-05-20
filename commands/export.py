import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import click

from lib.constants import ASSETS_DIR
from lib.pipeline import Pipeline
from lib.utils import SHA_RE, interruptible, source_file

_DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})")
_YEAR_RE = re.compile(r"^\d{4}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
UNDATED = "undated"


def _same_size_and_mtime(src: Path, dest: Path) -> bool:
    """Cheap idempotency check for previously-exported files.

    `shutil.copy2` preserves mtime, so a prior run leaves the destination with
    a matching size and (whole-second) mtime. Comparing at second granularity
    tolerates filesystems with coarser mtime resolution than the source's.
    """
    src_stat = src.stat()
    dest_stat = dest.stat()
    return src_stat.st_size == dest_stat.st_size and int(src_stat.st_mtime) == int(
        dest_stat.st_mtime
    )


def _bucket_dir(output_dir: Path, stem: str) -> Path:
    """Return the YYYY/YYYY-MM/ (or undated/) subdir for a note stem."""
    m = _DATE_PREFIX_RE.match(stem)
    if m:
        year, month = m.group(1), f"{m.group(1)}-{m.group(2)}"
        return output_dir / year / month
    return output_dir / UNDATED


def _iter_managed_files(output_dir: Path) -> Iterator[Path]:
    """Yield files under output_dir that belong to the export's managed layout.

    Managed = top-level files (legacy from the flat layout), files in
    YYYY/YYYY-MM/, and files in undated/. Anything else is left alone.
    """
    for entry in output_dir.iterdir():
        if entry.is_file():
            yield entry
            continue
        if not entry.is_dir():
            continue
        if entry.name == UNDATED:
            for f in entry.iterdir():
                if f.is_file():
                    yield f
        elif _YEAR_RE.match(entry.name):
            for month_dir in entry.iterdir():
                if month_dir.is_dir() and _MONTH_RE.match(month_dir.name):
                    for f in month_dir.iterdir():
                        if f.is_file():
                            yield f


def _prune_empty_managed_dirs(output_dir: Path) -> None:
    """Remove empty YYYY-MM, YYYY, and undated dirs after cleanup."""
    for entry in output_dir.iterdir():
        if not entry.is_dir():
            continue
        if entry.name == UNDATED:
            if not any(entry.iterdir()):
                entry.rmdir()
        elif _YEAR_RE.match(entry.name):
            for month_dir in list(entry.iterdir()):
                if (
                    month_dir.is_dir()
                    and _MONTH_RE.match(month_dir.name)
                    and not any(month_dir.iterdir())
                ):
                    month_dir.rmdir()
            if not any(entry.iterdir()):
                entry.rmdir()


def _export_path(vault: Path, output_dir: Path, path: str) -> None:
    """Export sources for one vault subdir into output_dir/{path}/."""
    path_dir = vault / path
    export_root = output_dir / path

    export_root.mkdir(parents=True, exist_ok=True)

    exported = 0
    unchanged = 0
    missing = 0
    written: set[Path] = set()
    for md in interruptible(sorted(path_dir.glob("*.md"))):
        text = md.read_text()
        seen: set[str] = set()
        shas: list[str] = []
        for sha in SHA_RE.findall(text):
            if sha not in seen:
                seen.add(sha)
                shas.append(sha)
        if not shas:
            continue
        for i, sha in enumerate(shas):
            src = source_file(path_dir / ASSETS_DIR / sha)
            if src is None:
                click.secho(f"  Missing source: {md.name} ({sha[:12]}…)", fg="yellow")
                missing += 1
                continue
            suffix = src.suffix.lower()
            stem = md.stem if i == 0 else f"{md.stem}-{sha[:12]}"
            dest_dir = _bucket_dir(export_root, md.stem)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{stem}{suffix}"
            if dest.exists() and _same_size_and_mtime(src, dest):
                written.add(dest)
                unchanged += 1
                continue
            shutil.copy2(src, dest)
            written.add(dest)
            rel = dest.relative_to(output_dir)
            click.secho(f"  Exported: {rel}", fg="green")
            exported += 1

    removed = 0
    for existing in sorted(_iter_managed_files(export_root)):
        if existing not in written:
            rel = existing.relative_to(output_dir)
            existing.unlink()
            click.secho(f"  Removed: {rel}", fg="green")
            removed += 1
    _prune_empty_managed_dirs(export_root)

    parts = []
    if exported:
        parts.append(f"{exported} exported")
    if unchanged:
        parts.append(f"{unchanged} unchanged")
    if removed:
        parts.append(f"{removed} removed")
    if missing:
        parts.append(f"{missing} missing")
    if parts:
        click.secho(", ".join(parts), bold=True)


_OUTPUT_DIR_OPTION = click.option(
    "--output-dir",
    envvar="OBAGENT_EXPORT",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Export root; the per-type subdir (e.g. Documents/, Receipts/) is appended.",
)


@click.command()
@_OUTPUT_DIR_OPTION
@click.pass_context
def export(ctx, output_dir: Path):
    """Export source files under --output-dir/{path}, grouped by year/month."""
    _export_path(Path(ctx.obj["vault"]), output_dir, ctx.obj["path"])


@click.command("export")
@_OUTPUT_DIR_OPTION
@click.pass_context
def export_all(ctx, output_dir: Path):
    """Export source files for every document type under --output-dir/{type}/."""
    vault = Path(ctx.obj["vault"])
    for pipeline in Pipeline._registry:
        path = pipeline.default_path
        click.secho(f"\n=== {pipeline.name.title()} ({path}) ===", bold=True)
        _export_path(vault, output_dir, path)
