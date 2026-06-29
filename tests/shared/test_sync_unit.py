from collections import defaultdict

from commands.notion import backfill as bf
from commands.notion import sync
from lib.notion_api import NotionClient

R = "receipt"
USD12 = {"Total": {"number": 12.0}, "Non-USD Total": {"rich_text": []}}
SHA = "a" * 64


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


def test_sync_command_invokes_run_sync(runner, monkeypatch):
    called = {}

    def fake_run_sync(client, vault, ds, *, dry_run, full):
        called.update(dry_run=dry_run, full=full, ds=ds)
        return {"unchanged": 3}

    monkeypatch.setattr(sync, "run_sync", fake_run_sync)
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("OBAGENT_NOTION_RECEIPT_DS", "rds")
    monkeypatch.setenv("OBAGENT_NOTION_DOCUMENT_DS", "dds")
    result = runner.invoke(sync.sync_command, ["--dry-run"], obj={"vault": "/tmp"})
    assert result.exit_code == 0, result.output
    assert called["dry_run"] is True and called["full"] is False
    assert called["ds"] == {"receipt": "rds", "document": "dds"}
    assert "unchanged" in result.output


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
