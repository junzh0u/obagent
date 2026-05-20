import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import click

from lib.constants import ASSETS_DIR
from lib.utils import SHA_RE, interruptible, source_file

_DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})")
_YEAR_RE = re.compile(r"^\d{4}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
UNDATED = "undated"


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


@click.command()
@click.option(
    "--output-dir",
    envvar="OBAGENT_DOCUMENT_EXPORT",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to export source files into.",
)
@click.pass_context
def export(ctx, output_dir: Path):
    """Export source files to --output-dir, grouped by year/month."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    path_dir = vault / path

    output_dir.mkdir(parents=True, exist_ok=True)

    exported = 0
    skipped = 0
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
                skipped += 1
                continue
            suffix = src.suffix.lower()
            stem = md.stem if i == 0 else f"{md.stem}-{sha[:12]}"
            dest_dir = _bucket_dir(output_dir, md.stem)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{stem}{suffix}"
            shutil.copy2(src, dest)
            written.add(dest)
            rel = dest.relative_to(output_dir)
            click.secho(f"  Exported: {rel}", fg="green")
            exported += 1

    removed = 0
    for existing in sorted(_iter_managed_files(output_dir)):
        if existing not in written:
            rel = existing.relative_to(output_dir)
            existing.unlink()
            click.secho(f"  Removed: {rel}", fg="green")
            removed += 1
    _prune_empty_managed_dirs(output_dir)

    parts = []
    if exported:
        parts.append(f"{exported} exported")
    if removed:
        parts.append(f"{removed} removed")
    if skipped:
        parts.append(f"{skipped} skipped")
    if parts:
        click.secho(", ".join(parts), bold=True)
