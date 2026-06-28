import email.message
import io
import urllib.error

import pytest

from lib import notion_api
from lib.notion_api import NotionClient, NotionError, truncate_u16, u16len


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never actually sleep during retry/throttle tests."""
    monkeypatch.setattr(notion_api.time, "sleep", lambda *a, **k: None)


class _Resp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _http_error(code, body=b"", retry_after=None):
    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://api.notion.com/v1/x", code, "err", hdrs, io.BytesIO(body)
    )


def _patch_urlopen(monkeypatch, side_effects):
    """Patch urlopen to return/raise each item in ``side_effects`` in turn."""
    seq = list(side_effects)
    calls = {"n": 0}

    def fake(req, timeout=None):
        item = seq[calls["n"]]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(notion_api.urllib.request, "urlopen", fake)
    return calls


# --- UTF-16 helpers -------------------------------------------------------


def test_u16len_counts_code_units():
    assert u16len("abc") == 3
    assert u16len("héllo") == 5
    assert u16len("😀") == 2  # astral char = surrogate pair = 2 units


def test_truncate_u16_respects_limit_and_astral_chars():
    assert truncate_u16("abcdef", 3) == "abc"
    assert truncate_u16("abc", 10) == "abc"
    # Must not split an emoji into half a surrogate pair.
    out = truncate_u16("😀😀😀", 3)
    assert out == "😀"
    assert u16len(out) <= 3


# --- api() retry policy ---------------------------------------------------


def test_api_success_returns_parsed_json(monkeypatch):
    _patch_urlopen(monkeypatch, [_Resp(b'{"ok": true}')])
    assert NotionClient(token="t").api("GET", f"{notion_api.API}/x") == {"ok": True}


def test_api_retries_on_429(monkeypatch):
    calls = _patch_urlopen(
        monkeypatch,
        [_http_error(429, b"rate limited", retry_after="1"), _Resp(b'{"ok": 1}')],
    )
    assert NotionClient(token="t").api("POST", f"{notion_api.API}/x", data={}) == {
        "ok": 1
    }
    assert calls["n"] == 2


def test_api_retries_on_cloudflare_403(monkeypatch):
    calls = _patch_urlopen(
        monkeypatch,
        [_http_error(403, b"<html>/cdn-cgi/ Cloudflare</html>"), _Resp(b'{"ok": 1}')],
    )
    assert NotionClient(token="t").api("GET", f"{notion_api.API}/x") == {"ok": 1}
    assert calls["n"] == 2


def test_api_retries_on_5xx(monkeypatch):
    calls = _patch_urlopen(
        monkeypatch, [_http_error(500, b"boom"), _Resp(b'{"ok": 1}')]
    )
    assert NotionClient(token="t").api("GET", f"{notion_api.API}/x") == {"ok": 1}
    assert calls["n"] == 2


def test_api_raises_on_real_4xx_without_retry(monkeypatch):
    calls = _patch_urlopen(
        monkeypatch,
        [
            _http_error(400, b'{"object":"error","message":"bad"}'),
            _Resp(b'{"unreached": 1}'),
        ],
    )
    with pytest.raises(NotionError):
        NotionClient(token="t").api("POST", f"{notion_api.API}/x", data={})
    assert calls["n"] == 1  # genuine 4xx is not retried


# --- upload_file ----------------------------------------------------------


def test_upload_file_single_part(monkeypatch, tmp_path):
    f = tmp_path / "small.pdf"
    f.write_bytes(b"hello")
    client = NotionClient(token="t")
    seen = []

    def fake_api(method, url, *, data=None, headers=None, raw=False):
        seen.append(url)
        return {"id": "uid-1"} if url.endswith("/file_uploads") else {}

    monkeypatch.setattr(client, "api", fake_api)
    assert client.upload_file(f, "small.pdf") == "uid-1"
    assert seen == [
        f"{notion_api.API}/file_uploads",
        f"{notion_api.API}/file_uploads/uid-1/send",
    ]  # create + send, no /complete


def test_upload_file_multipart(monkeypatch, tmp_path):
    # Shrink the thresholds so a tiny file exercises the multipart path.
    monkeypatch.setattr(notion_api, "SINGLE_MAX", 10)
    monkeypatch.setattr(notion_api, "PART_SIZE", 4)
    f = tmp_path / "big.pdf"
    f.write_bytes(b"x" * 25)  # > 10 -> multipart; ceil(25/4) = 7 parts
    client = NotionClient(token="t")
    created = {}
    seen = []

    def fake_api(method, url, *, data=None, headers=None, raw=False):
        seen.append(url)
        if url.endswith("/file_uploads"):
            created["data"] = data
            return {"id": "uid-2"}
        return {}

    monkeypatch.setattr(client, "api", fake_api)
    assert client.upload_file(f, "big.pdf") == "uid-2"
    assert created["data"]["mode"] == "multi_part"
    assert created["data"]["number_of_parts"] == 7
    assert len([u for u in seen if u.endswith("/send")]) == 7
    assert any(u.endswith("/complete") for u in seen)


# --- page / query wrappers ------------------------------------------------


def _record_api(client, monkeypatch, response=None):
    """Patch client.api to record (method, url, data) and return ``response``."""
    calls = []

    def fake_api(method, url, *, data=None, headers=None, raw=False):
        calls.append({"method": method, "url": url, "data": data})
        return response if response is not None else {}

    monkeypatch.setattr(client, "api", fake_api)
    return calls


def test_create_page_uses_data_source_parent(monkeypatch):
    client = NotionClient(token="t")
    calls = _record_api(client, monkeypatch, {"id": "pg1"})
    props = {"Merchant": {"rich_text": [{"text": {"content": "Costco"}}]}}
    out = client.create_page("ds-123", props, children=[{"x": 1}])
    assert out == {"id": "pg1"}
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == f"{notion_api.API}/pages"
    assert calls[0]["data"]["parent"] == {
        "type": "data_source_id",
        "data_source_id": "ds-123",
    }
    assert calls[0]["data"]["properties"] == props
    assert calls[0]["data"]["children"] == [{"x": 1}]


def test_update_page_patches_properties(monkeypatch):
    client = NotionClient(token="t")
    calls = _record_api(client, monkeypatch, {"id": "pg1"})
    client.update_page("pg1", {"Total": {"number": 9.5}})
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"] == f"{notion_api.API}/pages/pg1"
    assert calls[0]["data"] == {"properties": {"Total": {"number": 9.5}}}


def test_query_builds_body_and_url(monkeypatch):
    client = NotionClient(token="t")
    calls = _record_api(client, monkeypatch, {"results": [], "has_more": False})
    flt = {"property": "Sha", "rich_text": {"contains": "abc"}}
    client.query("ds-9", filter=flt, page_size=25)
    assert calls[0]["url"] == f"{notion_api.API}/data_sources/ds-9/query"
    assert calls[0]["data"] == {"page_size": 25, "filter": flt}


def test_iter_pages_follows_pagination(monkeypatch):
    client = NotionClient(token="t")
    pages = [
        {"results": [{"id": "a"}, {"id": "b"}], "has_more": True, "next_cursor": "c1"},
        {"results": [{"id": "c"}], "has_more": False, "next_cursor": None},
    ]
    seen_cursors = []

    def fake_query(ds, *, filter=None, sorts=None, start_cursor=None, page_size=100):
        seen_cursors.append(start_cursor)
        return pages[len(seen_cursors) - 1]

    monkeypatch.setattr(client, "query", fake_query)
    ids = [p["id"] for p in client.iter_pages("ds-9")]
    assert ids == ["a", "b", "c"]
    assert seen_cursors == [None, "c1"]  # first page no cursor, then next_cursor
