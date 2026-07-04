from collections import defaultdict

from commands.notion import backfill as bf
from commands.notion import sync
from lib.notion_api import NotionClient
from tests.conftest import needs_case_sensitive_fs

R = "receipt"
USD12 = {"Total": {"number": 12.0}, "Non-USD Total": {"rich_text": []}}
SHA = "a" * 64
FRONT = {"merchant": "San Jose Library", "date": "2026-06-27", "total": "$0.00"}


class PruneClient(NotionClient):
    """Serves a fixed set of live rows per data source; records trashes. Any GET
    (vault-only candidate) returns a configured live page."""

    def __init__(self, pages_by_ds, gets=None):
        super().__init__(token="test")
        self.pages_by_ds = pages_by_ds
        self.gets = gets or {}
        self.trashed: list[str] = []
        self.updated: list[tuple[str, dict]] = []
        self.uploaded: list[tuple[str, str]] = []

    def iter_pages(self, data_source_id, *, filter=None, sorts=None, page_size=100):
        yield from self.pages_by_ds.get(data_source_id, [])

    def trash_page(self, page_id):
        self.trashed.append(page_id)
        return {"id": page_id, "in_trash": True}

    def update_page(self, page_id, properties):
        self.updated.append((page_id, properties))
        return {"id": page_id}

    def upload_file(self, path, display_name):
        self.uploaded.append((str(path), display_name))
        return f"upload-{len(self.uploaded)}"

    def api(self, method, url, *, data=None, headers=None, raw=False):
        if method == "GET" and url.rsplit("/", 1)[-1] in self.gets:
            return self.gets[url.rsplit("/", 1)[-1]]
        raise AssertionError(f"unexpected api call {method} {url}")


def _rt(s):
    """A rich_text property in the *read* shape Notion returns (with 'type')."""
    return {"type": "rich_text", "rich_text": [{"plain_text": s}] if s else []}


def _page(nid, le="2020-01-01T00:00:00.000Z", front=FRONT):
    # Read-shape page properties (what the API returns), so read_editable inverts
    # cleanly and the merge is a no-op for an unchanged row.
    return {
        "id": nid,
        "last_edited_time": le,
        "properties": {
            "Merchant": _rt(front["merchant"]),
            "Date": {"type": "date", "date": {"start": front["date"]}},
            "Total": {"type": "number", "number": float(front["total"].lstrip("$"))},
            "Non-USD Total": _rt(""),
        },
    }


def _linked_receipt(receipts_dir, name, sha, notion_id, front=FRONT):
    """A linked receipt note + its source asset, returning the note path."""
    src = receipts_dir / "_assets_" / sha / "src"
    src.mkdir(parents=True)
    (src / "original.pdf").write_bytes(b"%PDF-1.4 fake")
    p = receipts_dir / f"{name}.md"
    p.write_text(
        f"---\nmerchant: {front['merchant']}\ndate: {front['date']}\n"
        f"total: {front['total']}\nconsumed_at: 2026-06-29T06:33:10+00:00\n"
        f"notion_id: {notion_id}\n---\n![[_assets_/{sha}/src/original.pdf]]\n"
    )
    return p


class FakeClient(NotionClient):
    """Records create/upload/query calls for create_unlinked tests."""

    def __init__(self, existing: str | None = None):
        super().__init__(token="test")
        self.existing = existing  # page id query should return, or None
        self.created: list[tuple[str, dict]] = []
        self.uploaded: list[tuple[str, str]] = []

    def query(
        self,
        data_source_id,
        *,
        filter=None,
        sorts=None,
        start_cursor=None,
        page_size=100,
    ):
        return {"results": [{"id": self.existing}] if self.existing else []}

    def upload_file(self, path, display_name):
        self.uploaded.append((str(path), display_name))
        return f"upload-{len(self.uploaded)}"

    def create_page(self, data_source_id, properties, *, children=None):
        self.created.append((data_source_id, properties))
        return {"id": "new-page-id", "properties": properties}


def _make_receipt(receipts_dir, *, notion_id=""):
    """A receipt note + its source asset, returning the note path."""
    src = receipts_dir / "_assets_" / SHA / "src"
    src.mkdir(parents=True)
    (src / "original.pdf").write_bytes(b"%PDF-1.4 fake")
    nid = f"notion_id: {notion_id}\n" if notion_id else ""
    p = receipts_dir / "2026-06-27 - San Jose Library - $0.00.md"
    p.write_text(
        "---\nmerchant: San Jose Library\ndate: 2026-06-27\ntotal: $0.00\n"
        f"consumed_at: 2026-06-29T06:33:10+00:00\n{nid}---\n"
        f"![[_assets_/{SHA}/src/original.pdf]]\n"
    )
    return p


def _base():
    return {"merchant": "X", "date": "2020-01-01", "total": "$10.00"}


# -- merge_fields (3-way) --------------------------------------------------


def test_merge_agree():
    b = _base()
    vu, nu, sh, c = sync.merge_fields(R, b, dict(b), dict(b), "notion")
    assert vu == {} and nu == {} and c == []
    assert sh == b


def test_merge_notion_changed_adopts_to_vault():
    b = _base()
    vu, nu, sh, c = sync.merge_fields(R, b, dict(b), {**b, "total": "$12.00"}, "notion")
    assert vu == {"total": "$12.00"} and nu == {} and c == []
    assert sh["total"] == "$12.00"


def test_merge_vault_changed_pushes_to_notion():
    b = _base()
    vu, nu, sh, c = sync.merge_fields(R, b, {**b, "total": "$12.00"}, dict(b), "notion")
    assert vu == {} and nu == USD12 and c == []
    assert sh["total"] == "$12.00"


def test_merge_conflict_notion_wins():
    b = _base()
    vu, nu, sh, c = sync.merge_fields(
        R, b, {**b, "total": "$12.00"}, {**b, "total": "$15.00"}, "notion"
    )
    assert vu == {"total": "$15.00"}
    assert sh["total"] == "$15.00"
    assert c == [("total", "$12.00", "$15.00")]


def test_merge_conflict_vault_wins():
    b = _base()
    vu, nu, sh, c = sync.merge_fields(
        R, b, {**b, "total": "$12.00"}, {**b, "total": "$15.00"}, "vault"
    )
    assert nu == USD12
    assert sh["total"] == "$12.00"
    assert len(c) == 1


def test_merge_ignores_formatting():
    b = {"merchant": "X", "date": "2020-01-01", "total": "$10"}
    vu, nu, sh, c = sync.merge_fields(
        R, b, {**b, "total": "$10.00"}, {**b, "total": "$10"}, "notion"
    )
    assert vu == {} and nu == {}  # decimal formatting is not a change


# -- write_back ------------------------------------------------------------


def test_write_back_receipt_adopt_total_renames(tmp_path):
    d = tmp_path / "Receipts"
    d.mkdir()
    p = d / "2025-10-12 - Holiday Inn - ¥230.40.md"
    p.write_text(
        "---\nmerchant: Holiday Inn\ndate: 2025-10-12\ntotal: ¥230.40\n"
        "consumed_at: 2026-01-01T00:00:00+00:00\nnotion_id: pg-1\n---\n"
        "![[_assets_/abc/src/original.pdf#height]]\n"
        "![[_assets_/abc/src/metadata.json]]\n"
    )
    note = bf.gather_vault(d, "receipt")[0]
    new_path = sync.write_back(note, {"total": "CNY 230.40"}, "receipt")
    assert new_path.name == "2025-10-12 - Holiday Inn - CNY 230.40.md"
    assert not p.exists()
    text = new_path.read_text()
    assert "total: CNY 230.40" in text
    assert "notion_id: pg-1" in text  # preserved
    assert "consumed_at: 2026-01-01T00:00:00+00:00" in text  # preserved
    assert "![[_assets_/abc/src/original.pdf#height]]" in text  # embeds preserved


@needs_case_sensitive_fs
def test_write_back_does_not_rename_into_case_variant(tmp_path):
    """A title edit that would collide (case-only) with a sibling note does not
    rename into it — no case-colliding file is created."""
    d = tmp_path / "Receipts"
    d.mkdir()
    # Sibling already occupies the capitalized casing.
    sibling = d / "2025-10-12 - Holiday Inn - CNY 230.40.md"
    sibling.write_text(
        "---\nmerchant: Holiday Inn\ndate: 2025-10-12\ntotal: CNY 230.40\n"
        "consumed_at: 2026-01-01T00:00:00+00:00\nnotion_id: pg-sib\n---\n"
        "![[_assets_/sib/src/original.pdf#height]]\n"
    )
    own = d / "2025-10-12 - holiday inn - CNY 230.40.md"
    own.write_text(
        "---\nmerchant: holiday inn\ndate: 2025-10-12\ntotal: CNY 230.40\n"
        "consumed_at: 2026-01-01T00:00:00+00:00\nnotion_id: pg-own\n---\n"
        "![[_assets_/own/src/original.pdf#height]]\n"
    )
    note = next(n for n in bf.gather_vault(d, "receipt") if n.path == own)

    result = sync.write_back(note, {"merchant": "Holiday Inn"}, "receipt")

    # Stayed in place; content updated; no third (colliding) file created.
    assert result == own
    assert own.exists() and sibling.exists()
    assert "merchant: Holiday Inn" in own.read_text()
    assert sorted(p.name for p in d.glob("*.md")) == [
        "2025-10-12 - Holiday Inn - CNY 230.40.md",
        "2025-10-12 - holiday inn - CNY 230.40.md",
    ]


def test_sync_command_invokes_run_sync(runner, monkeypatch):
    called = {}

    def fake_run_sync(client, vault, ds, *, dry_run, full, prune):
        called.update(dry_run=dry_run, full=full, prune=prune, ds=ds)
        return {"unchanged": 3}

    monkeypatch.setattr(sync, "run_sync", fake_run_sync)
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("OBAGENT_NOTION_RECEIPT_DS", "rds")
    monkeypatch.setenv("OBAGENT_NOTION_DOCUMENT_DS", "dds")
    result = runner.invoke(sync.sync_command, ["--dry-run"], obj={"vault": "/tmp"})
    assert result.exit_code == 0, result.output
    assert called["dry_run"] is True and called["full"] is False
    assert called["prune"] is False
    assert called["ds"] == {"receipt": "rds", "document": "dds"}
    assert "unchanged" in result.output


def test_sync_command_passes_prune(runner, monkeypatch):
    called = {}

    def fake_run_sync(client, vault, ds, *, dry_run, full, prune):
        called.update(prune=prune)
        return {}

    monkeypatch.setattr(sync, "run_sync", fake_run_sync)
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("OBAGENT_NOTION_RECEIPT_DS", "rds")
    result = runner.invoke(sync.sync_command, ["--prune"], obj={"vault": "/tmp"})
    assert result.exit_code == 0, result.output
    assert called["prune"] is True


def test_backfill_command_invokes_run_backfill(runner, monkeypatch):
    calls = []

    def fake_run_backfill(client, vault, t, ds_id, *, dry_run, limit):
        calls.append((t, ds_id, dry_run, limit))
        return {"linked": 1}

    monkeypatch.setattr(sync, "run_backfill", fake_run_backfill)
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("OBAGENT_NOTION_RECEIPT_DS", "rds")
    monkeypatch.setenv("OBAGENT_NOTION_DOCUMENT_DS", "dds")
    result = runner.invoke(
        sync.backfill_command, ["--dry-run", "--limit", "5"], obj={"vault": "/tmp"}
    )
    assert result.exit_code == 0, result.output
    assert ("receipt", "rds", True, 5) in calls
    assert ("document", "dds", True, 5) in calls
    assert "linked" in result.output


def test_sync_command_requires_token(runner, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.setattr(sync, "run_sync", lambda *a, **k: {})
    result = runner.invoke(sync.sync_command, [], obj={"vault": "/tmp"})
    assert result.exit_code != 0
    assert "NOTION_TOKEN" in result.output


def test_sync_command_requires_data_sources(runner, monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.delenv("OBAGENT_NOTION_RECEIPT_DS", raising=False)
    monkeypatch.delenv("OBAGENT_NOTION_DOCUMENT_DS", raising=False)
    monkeypatch.setattr(sync, "run_sync", lambda *a, **k: {})
    result = runner.invoke(sync.sync_command, [], obj={"vault": "/tmp"})
    assert result.exit_code != 0
    assert "data source" in result.output.lower()


def test_write_back_document_adopts_summary_and_tags(tmp_path):
    d = tmp_path / "Documents"
    d.mkdir()
    p = d / "2027-01-31 - Card.md"
    p.write_text(
        "---\ntitle: Card\ndate: 2027-01-31\ntags:\n  - old\npeople:\n"
        "consumed_at: x\nnotion_id: pg-2\n---\n"
        "> [!summary]\n> Old summary.\n\n"
        "![[_assets_/d/src/original.pdf]]\n"
    )
    note = bf.gather_vault(d, "document")[0]
    sync.write_back(note, {"tags": "new,zoo", "summary": "New summary."}, "document")
    text = p.read_text()  # title/date unchanged -> no rename
    assert "New summary." in text
    assert "- new" in text and "- zoo" in text
    assert "notion_id: pg-2" in text
    assert "![[_assets_/d/src/original.pdf]]" in text


# -- create_unlinked (push new notes to Notion) ----------------------------


def test_create_unlinked_creates_row_and_links(tmp_path):
    (tmp_path / "Receipts").mkdir()
    p = _make_receipt(tmp_path / "Receipts")
    client = FakeClient(existing=None)
    shadow: dict[str, dict[str, str]] = {}
    stats: defaultdict[str, int] = defaultdict(int)
    sync.create_unlinked(client, tmp_path, {R: "rds"}, shadow, stats, dry_run=False)

    assert stats["created"] == 1
    ds_id, props = client.created[0]
    assert ds_id == "rds"
    # editable fields + machine props + the file are all on the new row
    assert {"Merchant", "Date", "Total", "Sha", "Consumed At", "File"} <= props.keys()
    assert client.uploaded[0][1] == p.stem + ".pdf"  # source uploaded, nice name
    assert "notion_id: new-page-id" in p.read_text()  # id written back
    assert shadow["new-page-id"]["merchant"] == "San Jose Library"
    assert shadow["new-page-id"]["total"] == "$0.00"


def test_create_unlinked_adopts_existing_by_sha(tmp_path):
    (tmp_path / "Receipts").mkdir()
    p = _make_receipt(tmp_path / "Receipts")
    client = FakeClient(existing="existing-id")  # a row already bears this sha
    shadow: dict[str, dict[str, str]] = {}
    stats: defaultdict[str, int] = defaultdict(int)
    sync.create_unlinked(client, tmp_path, {R: "rds"}, shadow, stats, dry_run=False)

    assert stats["adopted"] == 1
    assert client.created == []  # no duplicate row
    assert client.uploaded == []  # no re-upload on adopt
    assert "notion_id: existing-id" in p.read_text()
    assert shadow["existing-id"]["merchant"] == "San Jose Library"


def test_create_unlinked_dry_run_writes_nothing(tmp_path):
    (tmp_path / "Receipts").mkdir()
    p = _make_receipt(tmp_path / "Receipts")
    client = FakeClient(existing=None)
    shadow: dict[str, dict[str, str]] = {}
    stats: defaultdict[str, int] = defaultdict(int)
    sync.create_unlinked(client, tmp_path, {R: "rds"}, shadow, stats, dry_run=True)

    assert stats["would_create"] == 1
    assert client.created == [] and client.uploaded == []
    assert "notion_id" not in p.read_text()
    assert shadow == {}


def test_create_unlinked_skips_already_linked(tmp_path):
    (tmp_path / "Receipts").mkdir()
    _make_receipt(tmp_path / "Receipts", notion_id="pg-existing")
    client = FakeClient(existing=None)
    shadow: dict[str, dict[str, str]] = {}
    stats: defaultdict[str, int] = defaultdict(int)
    sync.create_unlinked(client, tmp_path, {R: "rds"}, shadow, stats, dry_run=False)

    assert client.created == [] and client.uploaded == []
    assert stats.get("created", 0) == 0 and shadow == {}


# -- prune: deletion propagation (--prune) ---------------------------------


def test_prune_deletes_vault_note_when_row_trashed(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    a = _linked_receipt(rec, "A", "a" * 64, "pg-A")
    b = _linked_receipt(rec, "B", "b" * 64, "pg-B")
    bf.save_shadow(tmp_path, {"pg-A": FRONT, "pg-B": FRONT})
    # Only pg-A is still live; pg-B was trashed in Notion.
    client = PruneClient({"rds": [_page("pg-A")]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, prune=True)

    assert stats.get("vault_deleted") == 1
    assert a.exists() and not b.exists()
    assert (rec / "_assets_" / ("a" * 64)).exists()
    assert not (rec / "_assets_" / ("b" * 64)).exists()  # source file gone too
    assert client.trashed == []


def test_prune_dry_run_keeps_vault_note(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    a = _linked_receipt(rec, "A", "a" * 64, "pg-A")
    b = _linked_receipt(rec, "B", "b" * 64, "pg-B")
    bf.save_shadow(tmp_path, {"pg-A": FRONT, "pg-B": FRONT})
    client = PruneClient({"rds": [_page("pg-A")]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, prune=True, dry_run=True)

    assert stats.get("would_delete_vault") == 1
    assert a.exists() and b.exists()  # nothing actually deleted


def test_prune_skips_delete_when_zero_live_rows(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    a = _linked_receipt(rec, "A", "a" * 64, "pg-A")
    bf.save_shadow(tmp_path, {"pg-A": FRONT})
    # Data source returns nothing (bad id / outage) — must NOT wipe the vault.
    client = PruneClient({"rds": []}, gets={"pg-A": _page("pg-A")})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, prune=True)

    assert "vault_deleted" not in stats
    assert a.exists()


def test_prune_trashes_row_when_vault_note_deleted(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    d = _linked_receipt(rec, "D", "d" * 64, "pg-D")  # still present
    # pg-C was linked (in the shadow) but its vault note is gone.
    bf.save_shadow(tmp_path, {"pg-C": FRONT, "pg-D": FRONT})
    client = PruneClient({"rds": [_page("pg-C"), _page("pg-D")]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, prune=True)

    assert stats.get("notion_trashed") == 1
    assert client.trashed == ["pg-C"]
    assert d.exists()  # the surviving note untouched


def test_prune_dry_run_does_not_trash(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    _linked_receipt(rec, "D", "d" * 64, "pg-D")
    bf.save_shadow(tmp_path, {"pg-C": FRONT, "pg-D": FRONT})
    client = PruneClient({"rds": [_page("pg-C"), _page("pg-D")]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, prune=True, dry_run=True)

    assert stats.get("would_trash_notion") == 1
    assert client.trashed == []


def test_prune_skips_trash_when_vault_empty(tmp_path):
    (tmp_path / "Receipts").mkdir()  # no notes at all
    bf.save_shadow(tmp_path, {"pg-C": FRONT})
    client = PruneClient({"rds": [_page("pg-C")]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, prune=True)

    assert client.trashed == []  # empty-vault guard prevented a mass-trash
    assert "notion_trashed" not in stats


def test_no_prune_leaves_deletions_alone(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    a = _linked_receipt(rec, "A", "a" * 64, "pg-A")
    bf.save_shadow(tmp_path, {"pg-A": FRONT, "pg-B": FRONT})
    # pg-B's note is already gone and pg-B's row is live; without --prune nothing
    # destructive happens in either direction.
    client = PruneClient({"rds": [_page("pg-A"), _page("pg-B")]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, full=True)

    assert a.exists()
    assert client.trashed == []
    assert "vault_deleted" not in stats and "notion_trashed" not in stats


# -- _upload_sources naming (per-file sync identity) -----------------------


def _multifile_note(rec, name, shas):
    for sha in shas:
        (rec / "_assets_" / sha / "src").mkdir(parents=True)
        (rec / "_assets_" / sha / "src" / "original.pdf").write_bytes(b"%PDF")
    embeds = "".join(f"![[_assets_/{sha}/src/original.pdf]]\n" for sha in shas)
    p = rec / f"{name}.md"
    p.write_text(
        "---\nmerchant: X\ndate: 2026-06-27\ntotal: $0.00\nnotion_id: pg-1\n---\n"
        + embeds
    )
    return bf.gather_vault(rec, "receipt")[0]


def test_upload_sources_multifile_encodes_sha(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    note = _multifile_note(rec, "note", ["a" * 64, "b" * 64])
    pairs = bf.upload_sources(FakeClient(), tmp_path, "receipt", note)
    assert sorted(n for _, n in pairs) == [
        "note-aaaaaaaaaaaa.pdf",
        "note-bbbbbbbbbbbb.pdf",
    ]


def test_upload_sources_singlefile_keeps_clean_name(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    note = _multifile_note(rec, "solo", ["a" * 64])  # one source -> no sha suffix
    pairs = bf.upload_sources(FakeClient(), tmp_path, "receipt", note)
    assert [n for _, n in pairs] == ["solo.pdf"]


# -- stage 2: vault->Notion file push on Sha drift -------------------------


def _row_with_files(nid, sha_text, file_names):
    return {
        "id": nid,
        "last_edited_time": "2020-01-01T00:00:00.000Z",
        "properties": {
            **_page(nid)["properties"],
            "Sha": _rt(sha_text),
            "File": {"files": [{"name": n} for n in file_names]},
        },
    }


def test_sync_pushes_files_when_source_set_changed(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    _linked_receipt(rec, "R", "a" * 64, "pg-1")  # vault has ONE source now
    bf.save_shadow(tmp_path, {"pg-1": FRONT})
    # Row still records {a, b} + both old attachments (vault dropped b).
    page = _row_with_files(
        "pg-1",
        "\n".join(["a" * 64, "b" * 64]),
        ["R-aaaaaaaaaaaa.pdf", "R-bbbbbbbbbbbb.pdf"],
    )
    client = PruneClient({"rds": [page]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"})

    assert stats.get("files_pushed") == 1
    assert len(client.uploaded) == 1  # current single source re-uploaded
    pushed = [p for _pid, p in client.updated if "File" in p]
    assert len(pushed) == 1
    assert pushed[0]["Sha"]["rich_text"][0]["text"]["content"] == "a" * 64
    assert [f["name"] for f in pushed[0]["File"]["files"]] == ["R.pdf"]


def test_sync_no_file_push_when_in_sync(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    _linked_receipt(rec, "R", "a" * 64, "pg-1")
    bf.save_shadow(tmp_path, {"pg-1": FRONT})
    page = _row_with_files("pg-1", "a" * 64, ["R.pdf"])  # Sha matches note.shas
    client = PruneClient({"rds": [page]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"})

    assert "files_pushed" not in stats
    assert client.uploaded == []


def test_sync_dry_run_reports_file_push(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    _linked_receipt(rec, "R", "a" * 64, "pg-1")
    bf.save_shadow(tmp_path, {"pg-1": FRONT})
    page = _row_with_files(
        "pg-1",
        "\n".join(["a" * 64, "b" * 64]),
        ["R-aaaaaaaaaaaa.pdf", "R-bbbbbbbbbbbb.pdf"],
    )
    client = PruneClient({"rds": [page]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, dry_run=True)

    assert stats.get("would_push_files") == 1
    assert client.uploaded == [] and client.updated == []


# -- stage 4: --prune Notion->vault per-file delete ------------------------


def _multifile_front(rec, name, shas, nid="pg-1"):
    for sha in shas:
        (rec / "_assets_" / sha / "src").mkdir(parents=True)
        (rec / "_assets_" / sha / "src" / "original.pdf").write_bytes(b"%PDF")
    embeds = "".join(f"![[_assets_/{s}/src/original.pdf]]\n" for s in shas)
    (rec / f"{name}.md").write_text(
        f"---\nmerchant: {FRONT['merchant']}\ndate: {FRONT['date']}\n"
        f"total: {FRONT['total']}\nconsumed_at: x\nnotion_id: {nid}\n---\n" + embeds
    )


def test_prune_deletes_source_removed_in_notion(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    shas = ["a" * 64, "b" * 64]
    _multifile_front(rec, "R", shas)
    bf.save_shadow(tmp_path, {"pg-1": FRONT})
    # Row records both shas (base) but its File now has only a (b removed in Notion).
    page = _row_with_files("pg-1", "\n".join(shas), ["R-aaaaaaaaaaaa.pdf"])
    client = PruneClient({"rds": [page]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, prune=True)

    assert stats.get("vault_files_deleted") == 1
    assert not (rec / "_assets_" / ("b" * 64)).exists()  # b's scan deleted
    assert (rec / "_assets_" / ("a" * 64)).exists()  # a kept
    pushed = [p for _pid, p in client.updated if "File" in p]  # Sha/File re-pushed to a
    assert pushed and pushed[-1]["Sha"]["rich_text"][0]["text"]["content"] == "a" * 64


def test_prune_dry_run_reports_file_delete(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    shas = ["a" * 64, "b" * 64]
    _multifile_front(rec, "R", shas)
    bf.save_shadow(tmp_path, {"pg-1": FRONT})
    page = _row_with_files("pg-1", "\n".join(shas), ["R-aaaaaaaaaaaa.pdf"])
    client = PruneClient({"rds": [page]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, prune=True, dry_run=True)

    assert stats.get("would_delete_vault_files") == 1
    assert (rec / "_assets_" / ("b" * 64)).exists()  # nothing deleted
    assert client.uploaded == []


def test_prune_skips_file_delete_on_unparseable_name(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    shas = ["a" * 64, "b" * 64]
    _multifile_front(rec, "R", shas)
    bf.save_shadow(tmp_path, {"pg-1": FRONT})
    # A renamed (unparseable) File entry -> fail-safe skips the destructive delete.
    page = _row_with_files("pg-1", "\n".join(shas), ["renamed.pdf"])
    client = PruneClient({"rds": [page]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"}, prune=True)

    assert "vault_files_deleted" not in stats
    assert (rec / "_assets_" / ("a" * 64)).exists()
    assert (rec / "_assets_" / ("b" * 64)).exists()  # both sources kept


def test_sync_restores_file_removed_in_notion_without_prune(tmp_path):
    rec = tmp_path / "Receipts"
    rec.mkdir()
    shas = ["a" * 64, "b" * 64]
    _multifile_front(rec, "R", shas)
    bf.save_shadow(tmp_path, {"pg-1": FRONT})
    # File lost b in Notion, but Sha + vault still have both. WITHOUT --prune.
    page = _row_with_files("pg-1", "\n".join(shas), ["R-aaaaaaaaaaaa.pdf"])
    client = PruneClient({"rds": [page]})
    stats = sync.run_sync(client, tmp_path, {R: "rds"})  # no prune

    assert "vault_files_deleted" not in stats  # vault untouched
    assert (rec / "_assets_" / ("b" * 64)).exists()
    assert stats.get("files_pushed") == 1  # File re-uploaded -> b restored on the row
    assert len(client.uploaded) == 2
