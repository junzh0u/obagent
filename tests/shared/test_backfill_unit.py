from pathlib import Path

from commands.notion import backfill as bf


def _rich(s):
    return {"type": "rich_text", "rich_text": [{"plain_text": s}]}


def _title(s):
    return {"type": "title", "title": [{"plain_text": s}]}


def _date(s):
    return {"type": "date", "date": {"start": s, "end": None}}


def _number(n):
    return {"type": "number", "number": n}


# -- match keys ------------------------------------------------------------


def test_receipt_keys_match_usd():
    front = {"date": "2026-06-27", "merchant": "Costco", "total": "$103.75"}
    props = {
        "Merchant": _rich("Costco"),
        "Date": _date("2026-06-27"),
        "Total": _number(103.75),
        "Non-USD Total": {"type": "rich_text", "rich_text": []},
    }
    assert bf.vault_match_key("receipt", front) == bf.notion_match_key("receipt", props)


def test_receipt_keys_match_across_currency_format():
    """Legacy vault '¥3,775' and Notion 'JPY 3,775' must produce the SAME key."""
    front = {"date": "2025-09-23", "merchant": "LINE Friends", "total": "¥3,775"}
    props = {
        "Merchant": _rich("LINE Friends"),
        "Date": _date("2025-09-23"),
        "Total": _number(None),
        "Non-USD Total": _rich("JPY 3,775"),
    }
    key_v = bf.vault_match_key("receipt", front)
    key_n = bf.notion_match_key("receipt", props)
    assert key_v == key_n == ("2025-09-23", "LINE Friends", "3775.00")


def test_receipt_keys_match_decimal_format():
    """Vault '$600' and Notion number 600.0 ('$600.00') must match."""
    front = {"date": "2025-11-20", "merchant": "Goodwill", "total": "$600"}
    props = {
        "Merchant": _rich("Goodwill"),
        "Date": _date("2025-11-20"),
        "Total": _number(600.0),
        "Non-USD Total": {"type": "rich_text", "rich_text": []},
    }
    assert bf.vault_match_key("receipt", front) == bf.notion_match_key("receipt", props)


def test_receipt_keys_match_quoted_merchant():
    """Vault '76' and Notion '\"76\"' (quoted brand) must match."""
    front = {"date": "2018-07-21", "merchant": "76", "total": "$95.00"}
    props = {
        "Merchant": _rich('"76"'),
        "Date": _date("2018-07-21"),
        "Total": _number(95.0),
        "Non-USD Total": {"type": "rich_text", "rich_text": []},
    }
    assert bf.vault_match_key("receipt", front) == bf.notion_match_key("receipt", props)


def test_document_keys_match():
    front = {"title": "Jury Summons", "date": "2026-03-01"}
    props = {"Name": _title("Jury Summons"), "Date": _date("2026-03-01")}
    assert (
        bf.vault_match_key("document", front)
        == bf.notion_match_key("document", props)
        == ("Jury Summons", "2026-03-01")
    )


# -- classify --------------------------------------------------------------


def _note(key, name="n"):
    return bf.VaultNote(path=Path(f"/v/{name}.md"), key=key, shas=["s"], frontmatter={})


def _row(key, pid):
    return bf.NotionRow(page_id=pid, key=key, sha_text="")


def test_gather_vault_reads_summary_from_body(tmp_path):
    """Document summary lives in the body callout, not frontmatter."""
    d = tmp_path / "Documents"
    d.mkdir()
    (d / "2027-01-31 - Card.md").write_text(
        "---\ntitle: Card\ndate: 2027-01-31\ntags:\npeople:\nconsumed_at: x\n---\n"
        "> [!summary]\n> A membership card.\n\n"
        "![[_assets_/abc/src/original.pdf]]\n"
    )
    notes = bf.gather_vault(d, "document")
    assert len(notes) == 1
    assert notes[0].frontmatter["summary"] == "A membership card."


def test_inject_notion_id_idempotent():
    text = (
        "---\nmerchant: X\ndate: 2020-01-01\ntotal: $5\nconsumed_at: z\n---\n![[a]]\n"
    )
    out = bf.inject_notion_id(text, "pg-1")
    assert "notion_id: pg-1" in out.split("---")[1]  # inside frontmatter
    assert bf.inject_notion_id(out, "pg-1") == out  # no duplicate


def test_reconcile_total_notion_wins():
    note = bf.VaultNote(
        path=Path("/v/x.md"),
        key=(),
        shas=["s"],
        frontmatter={
            "merchant": "Holiday Inn",
            "date": "2025-10-12",
            "total": "¥230.40",
        },
    )
    ned = {"merchant": "Holiday Inn", "date": "2025-10-12", "total": "CNY 230.40"}
    vu, nu, sh = bf.reconcile("receipt", note, ned)
    assert vu == {"total": "CNY 230.40"}  # Notion wins -> adopt into vault
    assert nu == {}
    assert sh["total"] == "CNY 230.40"


def test_reconcile_merchant_quote_artifact_vault_wins():
    note = bf.VaultNote(
        path=Path("/v/x.md"),
        key=(),
        shas=["s"],
        frontmatter={"merchant": "76", "date": "2018-07-21", "total": "$95.00"},
    )
    ned = {"merchant": '"76"', "date": "2018-07-21", "total": "$95.00"}
    vu, nu, sh = bf.reconcile("receipt", note, ned)
    assert vu == {}  # vault wins (artifact)
    assert nu == {
        "Merchant": {"rich_text": [{"type": "text", "text": {"content": "76"}}]}
    }
    assert sh["merchant"] == "76"


def test_reconcile_agree():
    note = bf.VaultNote(
        path=Path("/v/x.md"),
        key=(),
        shas=["s"],
        frontmatter={"merchant": "Costco", "date": "2026-06-27", "total": "$103.75"},
    )
    ned = {"merchant": "Costco", "date": "2026-06-27", "total": "$103.75"}
    vu, nu, sh = bf.reconcile("receipt", note, ned)
    assert vu == {} and nu == {}
    assert sh == {"merchant": "Costco", "date": "2026-06-27", "total": "$103.75"}


def test_stem_receipt():
    stem = bf._stem(
        "receipt", {"merchant": "IKEA", "date": "2025-09-04", "total": "$341.69"}
    )
    assert stem == "2025-09-04 - IKEA - $341.69"


def test_classify_buckets():
    notes = [
        _note(("a",), "match"),  # matched
        _note(("vault_only",), "vonly"),  # vault-only -> create
        _note(("dup",), "d1"),  # ambiguous (two vault notes share key)
        _note(("dup",), "d2"),
    ]
    rows = [
        _row(("a",), "pg-a"),  # matched
        _row(("notion_only",), "pg-orphan"),  # orphan
        _row(("dup",), "pg-dup"),  # ambiguous
    ]
    rep = bf.classify(notes, rows)

    assert [(k, pid, p.name) for k, pid, p in rep.matched] == [
        (("a",), "pg-a", "match.md")
    ]
    assert [n.path.name for n in rep.vault_only] == ["vonly.md"]
    assert [(k, pid) for k, pid in rep.notion_only] == [(("notion_only",), "pg-orphan")]
    assert len(rep.ambiguous) == 1
    assert rep.ambiguous[0][0] == ("dup",)
