"""Low-level Notion API client (stdlib urllib only).

Lifted and trimmed from the migration importer (battle-tested over ~4,000 files):
the request throttle, the retry policy (429 / Cloudflare-WAF challenges / 408 /
409 / 5xx / socket timeouts), and multipart file upload. Plus Notion's UTF-16
length helpers for its text/name caps.

Scope is deliberately narrow: **transport + upload only**. No field mapping, no
page/query wrappers, no sync logic — those live in the ``commands/notion``
layer. obagent's pipeline/render core must not import this module (the Notion
dependency is one-directional).
"""

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API = "https://api.notion.com/v1"
# Proven version for file uploads + classic page ops. Data-source query/parent
# endpoints (M2) may require bumping this; revisit when those wrappers land.
NOTION_VERSION = "2022-06-28"

MIN_INTERVAL = 0.34  # ~3 req/s throttle
MAX_RETRIES = 8
REQUEST_TIMEOUT = 60  # essential: a stalled socket otherwise blocks forever
SINGLE_MAX = 20 * 1024 * 1024  # Notion single-part upload cap
PART_SIZE = 10 * 1024 * 1024  # 5–20 MB per part required (last may be smaller)

RICH_TEXT_LIMIT = 2000  # Notion rich_text property cap (UTF-16 code units)
FILE_NAME_LIMIT = 100  # Notion File-attachment name cap (UTF-16 code units)


def u16len(s: str) -> int:
    """Length in UTF-16 code units — how Notion measures text/name limits."""
    return len(s.encode("utf-16-le")) // 2


def truncate_u16(s: str, limit: int) -> str:
    """Truncate ``s`` to at most ``limit`` UTF-16 code units (astral-char safe)."""
    if u16len(s) <= limit:
        return s
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if u16len(s[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo]


class NotionError(RuntimeError):
    """A non-retryable Notion API error (a real 4xx, not a transient WAF page)."""


class NotionClient:
    """Thin Notion HTTP client: auth header, throttle, retry, file upload.

    The token defaults to ``$NOTION_TOKEN`` but may be injected (for tests).
    """

    def __init__(
        self, token: str | None = None, *, version: str = NOTION_VERSION
    ) -> None:
        self.token = (token or os.environ.get("NOTION_TOKEN", "")).strip()
        self.version = version
        self._last_req = 0.0

    # -- transport ---------------------------------------------------------
    def _throttle(self) -> None:
        dt = time.time() - self._last_req
        if dt < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - dt)
        self._last_req = time.time()

    def api(
        self,
        method: str,
        url: str,
        *,
        data: Any = None,
        headers: dict[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        """Make a Notion API call with throttle + retry.

        ``data`` is JSON-encoded unless ``raw`` (then it is sent verbatim, e.g.
        a multipart body). Returns the parsed JSON response. Raises
        ``NotionError`` on a genuine 4xx or after exhausting retries.
        """
        h = {"Authorization": f"Bearer {self.token}", "Notion-Version": self.version}
        if headers:
            h.update(headers)
        body = data
        if data is not None and not raw:
            body = json.dumps(data).encode()
            h.setdefault("Content-Type", "application/json")
        last: Exception | None = None
        for attempt in range(MAX_RETRIES):
            self._throttle()
            req = urllib.request.Request(url, data=body, headers=h, method=method)
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                code = e.code
                payload = e.read().decode(errors="replace")
                # Cloudflare CDN challenge/error pages are transient, not real
                # Notion API errors (which are JSON). Retry those, longer backoff.
                is_cdn = (
                    "/cdn-cgi/" in payload or "cloudflare" in payload[:3000].lower()
                )
                if code == 429:
                    wait = float(e.headers.get("Retry-After", "2"))
                    time.sleep(wait + 0.5)
                    continue
                if code in (408, 409) or code >= 500 or (code == 403 and is_cdn):
                    time.sleep(min(2**attempt + 2, 45))
                    continue
                raise NotionError(f"{method} {url} -> {code}\n{payload[:500]}") from e
            except OSError as e:  # timeouts, conn reset, DNS, etc.
                last = e
                time.sleep(2**attempt)
        raise NotionError(f"{method} {url} failed after {MAX_RETRIES} retries: {last}")

    # -- file upload -------------------------------------------------------
    def _send_part(
        self, uid: str, fields: dict[str, str], chunk: bytes, ctype: str
    ) -> None:
        boundary = "----obagentupload9b1c"
        parts: list[bytes] = []
        for k, v in fields.items():
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
            parts.append(f"{v}\r\n".encode())
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            b'Content-Disposition: form-data; name="file"; filename="blob"\r\n'
        )
        parts.append(f"Content-Type: {ctype}\r\n\r\n".encode())
        parts.append(chunk)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        self.api(
            "POST",
            f"{API}/file_uploads/{uid}/send",
            data=b"".join(parts),
            raw=True,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def upload_file(self, path: str | Path, display_name: str) -> str:
        """Upload a file and return its ``file_upload`` id.

        Single-shot for files ≤ 20 MB, otherwise multipart (10 MB parts +
        ``complete``). The JSON ``filename`` is the stored/download name
        (unicode-safe); the multipart part filename stays ASCII (``blob``) to
        avoid header-encoding issues.
        """
        path = Path(path)
        ctype = (
            mimetypes.guess_type(display_name)[0]
            or mimetypes.guess_type(path.name)[0]
            or "application/octet-stream"
        )
        size = path.stat().st_size
        if size <= SINGLE_MAX:
            up = self.api(
                "POST",
                f"{API}/file_uploads",
                data={"filename": display_name, "content_type": ctype},
            )
            uid = up["id"]
            with open(path, "rb") as f:
                self._send_part(uid, {}, f.read(), ctype)
            return uid
        nparts = (size + PART_SIZE - 1) // PART_SIZE
        up = self.api(
            "POST",
            f"{API}/file_uploads",
            data={
                "mode": "multi_part",
                "number_of_parts": nparts,
                "filename": display_name,
                "content_type": ctype,
            },
        )
        uid = up["id"]
        with open(path, "rb") as f:
            for pn in range(1, nparts + 1):
                self._send_part(uid, {"part_number": str(pn)}, f.read(PART_SIZE), ctype)
        self.api("POST", f"{API}/file_uploads/{uid}/complete", data={})
        return uid
