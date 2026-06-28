from commands.notion import backfill as bf
from commands.notion import sync

R = "receipt"
USD12 = {"Total": {"number": 12.0}, "Non-USD Total": {"rich_text": []}}


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
    result = runner.invoke(sync.sync_command, ["--dry-run"], obj={"vault": "/tmp"})
    assert result.exit_code == 0, result.output
    assert called["dry_run"] is True and called["full"] is False
    assert "receipt" in called["ds"] and "document" in called["ds"]
    assert "unchanged" in result.output


def test_sync_command_requires_token(runner, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.setattr(sync, "run_sync", lambda *a, **k: {})
    result = runner.invoke(sync.sync_command, [], obj={"vault": "/tmp"})
    assert result.exit_code != 0
    assert "NOTION_TOKEN" in result.output


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
