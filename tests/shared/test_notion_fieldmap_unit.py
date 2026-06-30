from lib import notion_fieldmap as fm


def _title(s):
    return {"type": "title", "title": [{"plain_text": s, "text": {"content": s}}]}


def _rich(s):
    return {
        "type": "rich_text",
        "rich_text": [{"plain_text": s, "text": {"content": s}}],
    }


def _date(s):
    return {"type": "date", "date": {"start": s, "end": None}}


def _number(n):
    return {"type": "number", "number": n}


def _multi(*names):
    return {"type": "multi_select", "multi_select": [{"name": n} for n in names]}


# -- low-level codecs ------------------------------------------------------


def test_read_plain_text():
    assert fm.read_plain_text(_title("Hello")) == "Hello"
    assert fm.read_plain_text(_rich("World")) == "World"
    assert fm.read_plain_text({"type": "rich_text", "rich_text": []}) == ""
    assert fm.read_plain_text({}) == ""


def test_norm_list_is_order_independent():
    assert fm._norm_list("b, a ,c") == "a,b,c"
    assert fm._norm_list("") == ""


# -- receipt fields --------------------------------------------------------


def test_receipt_usd_total_to_notion():
    props = fm.editable_properties(
        "receipt", {"merchant": "Costco", "date": "2026-06-27", "total": "$103.75"}
    )
    assert props["Merchant"] == {
        "rich_text": [{"type": "text", "text": {"content": "Costco"}}]
    }
    assert props["Date"] == {"date": {"start": "2026-06-27"}}
    assert props["Total"] == {"number": 103.75}
    assert props["Non-USD Total"] == {"rich_text": []}  # cleared for USD


def test_receipt_non_usd_total_to_notion():
    props = fm.editable_properties("receipt", {"total": "JPY 3,775"})
    assert props["Total"] == {"number": None}  # cleared for non-USD
    assert props["Non-USD Total"] == {
        "rich_text": [{"type": "text", "text": {"content": "JPY 3,775"}}]
    }


def test_receipt_read_editable_usd():
    page_props = {
        "Merchant": _rich("Costco"),
        "Date": _date("2026-06-27"),
        "Total": _number(103.75),
        "Non-USD Total": {"type": "rich_text", "rich_text": []},
    }
    assert fm.read_editable("receipt", page_props) == {
        "merchant": "Costco",
        "date": "2026-06-27",
        "total": "$103.75",
    }


def test_receipt_read_editable_non_usd():
    page_props = {
        "Merchant": _rich("LINE Friends"),
        "Date": _date("2025-09-23"),
        "Total": _number(None),
        "Non-USD Total": _rich("JPY 3,775"),
    }
    assert fm.read_editable("receipt", page_props)["total"] == "JPY 3,775"


def test_total_normalize():
    norm = next(f.normalize for f in fm.RECEIPT_FIELDS if f.vault_key == "total")
    # decimal / sign / separator formatting collapses
    assert norm("$2140") == norm("$2140.00") == "$|2140.00"
    assert norm("-$73.11") == norm("$-73.11") == "$|-73.11"
    assert norm("JPY 3,775") == norm("JPY 3775") == "JPY|3775.00"
    assert norm("RMB 66.00") == norm("CNY 66.00")  # alias -> canonical
    # currency stays distinct: legacy ¥ vs ISO surfaces as a real diff to adopt
    assert norm("¥230.40") != norm("CNY 230.40")


# -- document fields -------------------------------------------------------


def test_document_to_notion_and_back():
    front = {
        "title": "Membership Card",
        "date": "2027-01-31",
        "tags": "zoo,membership",
        "people": "Jun Zhou",
        "summary": "A membership card.",
    }
    props = fm.editable_properties("document", front)
    assert props["Name"] == {
        "title": [{"type": "text", "text": {"content": "Membership Card"}}]
    }
    assert props["Tags"] == {"multi_select": [{"name": "zoo"}, {"name": "membership"}]}
    assert props["People"] == {"multi_select": [{"name": "Jun Zhou"}]}

    page_props = {
        "Name": _title("Membership Card"),
        "Date": _date("2027-01-31"),
        "Tags": _multi("zoo", "membership"),
        "People": _multi("Jun Zhou"),
        "Summary": _rich("A membership card."),
    }
    assert fm.read_editable("document", page_props) == front


def test_tags_normalize_order_independent():
    norm = next(f.normalize for f in fm.DOCUMENT_FIELDS if f.vault_key == "tags")
    assert norm("membership,zoo") == norm("zoo,membership")


def test_bank_statement_not_synced():
    assert fm.editable_properties("bank_statement", {"bank_name": "X"}) == {}
    assert fm.read_editable("bank_statement", {}) == {}


# -- machine / structural properties ---------------------------------------


def test_sha_property_joins_set():
    assert fm.sha_property(["aaa", "bbb"]) == {
        "Sha": {"rich_text": [{"type": "text", "text": {"content": "aaa\nbbb"}}]}
    }


def test_consumed_at_property():
    assert fm.consumed_at_property("2026-02-23T18:32:14+00:00") == {
        "Consumed At": {"date": {"start": "2026-02-23T18:32:14+00:00"}}
    }
    assert fm.consumed_at_property("") == {"Consumed At": {"date": None}}


def test_file_property():
    assert fm.file_property([("uid1", "a.pdf"), ("uid2", "b.jpg")]) == {
        "File": {
            "files": [
                {"type": "file_upload", "file_upload": {"id": "uid1"}, "name": "a.pdf"},
                {"type": "file_upload", "file_upload": {"id": "uid2"}, "name": "b.jpg"},
            ]
        }
    }


def test_read_sha_parses_full_shas():
    props = {"Sha": _rich("\n".join([("a" * 64), ("b" * 64)]))}
    assert fm.read_sha(props) == {"a" * 64, "b" * 64}


def test_read_sha_empty():
    assert fm.read_sha({}) == set()


def test_read_file_sha12_parses_and_counts_unparseable():
    props = {
        "File": {
            "files": [
                {"name": "2026-06-27 - X-aaaaaaaaaaaa.pdf"},
                {"name": "2026-06-27 - X-bbbbbbbbbbbb.jpg"},
                {"name": "renamed-by-user.pdf"},  # no -<sha12> suffix
            ]
        }
    }
    shas, unparseable = fm.read_file_sha12(props)
    assert shas == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}
    assert unparseable == 1
