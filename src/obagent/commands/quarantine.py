"""Quarantine for inbox files that keep failing consume.

Consume leaves a failed source in the inbox for a retry next pass. A source that
can never succeed (a corrupt scan, a file the OCR service rejects) would then fail
every pass forever, so after ``max_attempts`` consecutive failures of the same
bytes (by sha) — or at once, for a file known to be unrecoverable — it is moved to
``{inbox root}/_failed/`` beside a ``.error.txt`` note saying why. Consume never
scans ``_failed/`` (it reads only loose root files and the type subdirs), and
``scripts/run.sh`` ends each clean pass on exit 3 while it is non-empty, so the
operator hears of it and moves a file back into the inbox to retry it or deletes
it to give up.

Attempt counts live in ``{vault}/.obagent/consume-failures.json``, keyed by sha;
a success, a duplicate skip, or the move itself clears the entry, so a file moved
back starts counting afresh.
"""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import click

QUARANTINE_DIR = "_failed"
FAILURES_FILE = ".obagent/consume-failures.json"
MAX_ATTEMPTS = 12  # ~1h of 5-min passes: rides out a short API outage
ERROR_SUFFIX = ".error.txt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Quarantine:
    """Per-run failure tracker; call :meth:`save` once the run is done.

    ``inbox_root`` is None (positional sources, ``--keep-original``) or
    ``max_attempts`` is 0 → failures are still counted but nothing is moved.
    """

    def __init__(self, vault: Path, inbox_root: Path | None, max_attempts: int):
        self._path = vault / FAILURES_FILE
        self._entries: dict[str, dict[str, str | int]] = (
            json.loads(self._path.read_text()) if self._path.exists() else {}
        )
        self._dirty = False
        self.dir = inbox_root / QUARANTINE_DIR if inbox_root and max_attempts else None
        self.max_attempts = max_attempts
        self.moved = 0

    def succeeded(self, sha: str) -> None:
        if self._entries.pop(sha, None) is not None:
            self._dirty = True

    def failed(self, source: Path, sha: str, error: str) -> None:
        """Count one failure; move ``source`` once it reaches ``max_attempts``."""
        now = _now()
        entry = self._entries.setdefault(sha, {"first_failed": now, "attempts": 0})
        entry.update(
            source=str(source),
            attempts=int(entry["attempts"]) + 1,
            last_failed=now,
            error=error,
        )
        self._dirty = True
        if self.dir and int(entry["attempts"]) >= self.max_attempts:
            self._move(
                source,
                sha,
                f"failed {entry['attempts']} consume attempts in a row "
                f"(first {entry['first_failed']}, last {now})",
                error,
            )

    def reject(self, source: Path, reason: str) -> bool:
        """Move a source that can never succeed right away. False when disabled."""
        if not self.dir:
            return False
        self._move(source, hashlib.sha256(source.read_bytes()).hexdigest(), reason, "")
        return True

    def _move(self, source: Path, sha: str, reason: str, error: str) -> None:
        assert self.dir is not None
        self.dir.mkdir(parents=True, exist_ok=True)
        dest = self.dir / source.name
        if dest.exists():
            dest = self.dir / f"{source.stem}-{sha[:12]}{source.suffix}"
        shutil.move(str(source), str(dest))
        lines = [
            f"{dest.name} was moved here by `obagent consume` at {_now()}.",
            f"Reason: {reason}.",
            f"Original location: {source}",
            f"sha256: {sha}",
        ]
        if error:
            lines.append(f"Last error: {error}")
        lines += [
            "",
            "To retry, move the file back into the consume inbox (its root, or a",
            "type folder to pin the type) and delete this note. To give up, delete",
            "both.",
        ]
        dest.with_name(dest.name + ERROR_SUFFIX).write_text("\n".join(lines) + "\n")
        if self._entries.pop(sha, None) is not None:
            self._dirty = True
        self.moved += 1
        click.secho(
            f"  Quarantined: {source.name} -> {dest} — {reason}"
            + (f"; last error: {error}" if error else ""),
            fg="red",
            bold=True,
        )

    def save(self) -> None:
        if not self._dirty:
            return
        if self._entries:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._entries, indent=2, sort_keys=True) + "\n"
            )
        else:
            self._path.unlink(missing_ok=True)
        self._dirty = False
