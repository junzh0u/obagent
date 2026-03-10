import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import click

from lib.constants import ASSETS_DIR, SUPPORTED_EXTENSIONS
from lib.utils import interruptible


def ingest_source(
    source: Path,
    vault: Path,
    path: str,
    *,
    keep_original: bool = False,
    overwrite: bool = False,
) -> Path | None:
    """Ingest a single source file into the vault.

    Returns target_dir on success, None if duplicate skipped.
    """
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    target_dir = vault / path / ASSETS_DIR / sha256
    if target_dir.exists() and not overwrite:
        click.secho(f"  Warning: already consumed ({sha256}), skipping", fg="yellow")
        return None
    src_dir = target_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    dest = src_dir / f"original{source.suffix.lower()}"
    if keep_original:
        shutil.copy2(source, dest)
    else:
        shutil.move(source, dest)
    metadata = {
        "original_filepath": str(source.resolve()),
        "sha256": sha256,
        "consumed_at": datetime.now(timezone.utc).isoformat(),
    }
    (src_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    click.secho(f"  Ingested -> {target_dir}", fg="green")
    return target_dir


def resolve_sources(paths: tuple[str, ...]) -> list[Path]:
    """Resolve a list of paths to supported source files, recursing into directories."""
    sources = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            sources.extend(
                sorted(
                    f
                    for f in p.rglob("*")
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                )
            )
        elif p.suffix.lower() in SUPPORTED_EXTENSIONS:
            sources.append(p)
        else:
            click.secho(f"Warning: skipping unsupported file: {p}", fg="yellow")
    return sources


@click.command()
@click.option(
    "--keep-original", is_flag=True, help="Copy files instead of moving them."
)
@click.option("--overwrite", is_flag=True, help="Overwrite existing entries.")
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@click.pass_context
def ingest(ctx, keep_original, overwrite, paths):
    """Ingest receipt files into the vault. Accepts files and/or directories."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    for source in interruptible(resolve_sources(paths)):
        click.secho(f"Ingest: {source}", bold=True)
        ingest_source(
            source, vault, path, keep_original=keep_original, overwrite=overwrite
        )
