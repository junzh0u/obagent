import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from commands.merchant import merchant
from commands.receipt.pipeline import ReceiptFields


def _write_md(vault, rel_path, content):
    md = vault / rel_path
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(content)
    return md


FM_TEMPLATE = (
    "---\nmerchant: {merchant}\ndate: 2024-01-15\n"
    "total: $42.50\nconsumed_at: 2024-01-15\n---\n"
    "Body text\n"
)


def _make_fm(merchant_name):
    return FM_TEMPLATE.format(merchant=merchant_name)


def _mock_confirm(answer):
    return patch(
        "lib.name_store.questionary.confirm",
        return_value=type("Q", (), {"ask": staticmethod(lambda: answer)})(),
    )


def _mock_select(answer):
    return patch(
        "lib.name_store.questionary.select",
        return_value=type("Q", (), {"ask": staticmethod(lambda: answer)})(),
    )


def _mock_text(answer):
    return patch(
        "lib.name_store.questionary.autocomplete",
        return_value=type("Q", (), {"ask": staticmethod(lambda: answer)})(),
    )


def _mock_checkbox(answer):
    return patch(
        "lib.name_store.questionary.checkbox",
        return_value=type("Q", (), {"ask": staticmethod(lambda: answer)})(),
    )


def test_rename_merchant(runner, vault):
    """Basic rename updates the merchant field."""
    md = _write_md(vault, "receipts/test.md", _make_fm("Starbucks"))

    with _mock_confirm(None):
        result = runner.invoke(
            merchant, ["rename", "Starbucks", "SBUX"], obj={"vault": str(vault)}
        )

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    content = md.read_text()
    assert "merchant: SBUX" in content
    assert "Starbucks" not in content


def test_rename_skips_unrelated(runner, vault):
    """Files without the old merchant name are not modified."""
    md = _write_md(vault, "receipts/test.md", _make_fm("Target"))

    result = runner.invoke(
        merchant, ["rename", "Starbucks", "SBUX"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output
    assert md.read_text() == _make_fm("Target")


def test_rename_no_frontmatter(runner, vault):
    """Files without frontmatter are skipped."""
    _write_md(vault, "receipts/test.md", "No frontmatter here.\n")

    result = runner.invoke(
        merchant, ["rename", "Starbucks", "SBUX"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output


def test_rename_skips_assets(runner, vault):
    """Files inside _assets_ directories are skipped."""
    _write_md(vault, "receipts/_assets_/abc/src/test.md", _make_fm("Starbucks"))

    result = runner.invoke(
        merchant, ["rename", "Starbucks", "SBUX"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output


def test_rename_multiple_files(runner, vault):
    """Rename updates across multiple files in different directories."""
    md1 = _write_md(vault, "receipts/a.md", _make_fm("Starbucks"))
    md2 = _write_md(vault, "other/b.md", _make_fm("Starbucks"))
    md3 = _write_md(vault, "receipts/c.md", _make_fm("Target"))

    with _mock_confirm(None):
        result = runner.invoke(
            merchant, ["rename", "Starbucks", "SBUX"], obj={"vault": str(vault)}
        )

    assert result.exit_code == 0
    assert "2 file(s) updated" in result.output
    assert "merchant: SBUX" in md1.read_text()
    assert "merchant: SBUX" in md2.read_text()
    assert "merchant: Target" in md3.read_text()


def test_rename_saves_to_aliases(runner, vault):
    """Confirming save writes the mapping to merchant-aliases.json."""
    _write_md(vault, "receipts/test.md", _make_fm("Starbucks"))

    with _mock_confirm(True):
        runner.invoke(
            merchant, ["rename", "Starbucks", "SBUX"], obj={"vault": str(vault)}
        )

    aliases_path = vault / ".obagent/merchant-aliases.json"
    assert aliases_path.exists()
    aliases = json.loads(aliases_path.read_text())
    assert aliases == {"Starbucks": "SBUX"}


def test_rename_declines_save(runner, vault):
    """Declining save does not create the aliases file."""
    _write_md(vault, "receipts/test.md", _make_fm("Starbucks"))

    with _mock_confirm(False):
        runner.invoke(
            merchant, ["rename", "Starbucks", "SBUX"], obj={"vault": str(vault)}
        )

    assert not (vault / ".obagent/merchant-aliases.json").exists()


def test_rename_no_save_when_zero_updates(runner, vault):
    """No save prompt when nothing was updated."""
    _write_md(vault, "receipts/test.md", _make_fm("Target"))

    result = runner.invoke(
        merchant, ["rename", "Starbucks", "SBUX"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output
    assert not (vault / ".obagent/merchant-aliases.json").exists()


def test_rename_interactive(runner, vault):
    """Interactive mode uses select and text prompts."""
    _write_md(vault, "receipts/test.md", _make_fm("Starbucks"))

    with _mock_select("Starbucks"), _mock_text("SBUX"), _mock_confirm(None):
        result = runner.invoke(merchant, ["rename"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output


def test_list_merchants(runner, vault):
    """Lists unique merchant names sorted."""
    _write_md(vault, "receipts/a.md", _make_fm("Target"))
    _write_md(vault, "receipts/b.md", _make_fm("Starbucks"))
    _write_md(vault, "receipts/c.md", _make_fm("Starbucks"))

    result = runner.invoke(merchant, ["list"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    lines = result.output.strip().split("\n")
    assert lines == ["Starbucks", "Target"]


def test_remap_from_explicit_path(runner, vault, tmp_path):
    """Remap with an explicit JSON mapping file."""
    md = _write_md(vault, "receipts/test.md", _make_fm("Starbucks"))
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps({"Starbucks": "SBUX"}))

    result = runner.invoke(
        merchant, ["remap", str(mapping_file)], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    assert "merchant: SBUX" in md.read_text()


def test_remap_from_default_path(runner, vault):
    """Remap from the default merchant-aliases.json."""
    md = _write_md(vault, "receipts/test.md", _make_fm("Starbucks"))
    aliases_dir = vault / ".obagent"
    aliases_dir.mkdir(parents=True, exist_ok=True)
    (aliases_dir / "merchant-aliases.json").write_text(
        json.dumps({"Starbucks": "SBUX"})
    )

    result = runner.invoke(merchant, ["remap"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    assert "merchant: SBUX" in md.read_text()


def test_remap_missing_file(runner, vault):
    """Error when no mapping file exists."""
    result = runner.invoke(merchant, ["remap"], obj={"vault": str(vault)})

    assert result.exit_code != 0
    assert "Mapping file not found" in result.output


def test_save_merges_with_existing(runner, vault):
    """Saving merges new mapping with existing aliases."""
    _write_md(vault, "receipts/test.md", _make_fm("Starbucks"))
    aliases_dir = vault / ".obagent"
    aliases_dir.mkdir(parents=True, exist_ok=True)
    (aliases_dir / "merchant-aliases.json").write_text(
        json.dumps({"CVS": "CVS Pharmacy"})
    )

    with _mock_confirm(True):
        runner.invoke(
            merchant, ["rename", "Starbucks", "SBUX"], obj={"vault": str(vault)}
        )

    aliases = json.loads((aliases_dir / "merchant-aliases.json").read_text())
    assert aliases == {"CVS": "CVS Pharmacy", "Starbucks": "SBUX"}


def test_postprocess_applies_alias():
    """ReceiptFields with _aliases renames merchant."""
    ReceiptFields._aliases = {"Starbucks": "SBUX"}
    try:
        fields = ReceiptFields(
            {"merchant": "Starbucks", "date": "2024-01-15", "total": "$42.50"}
        )
        assert fields["merchant"] == "SBUX"
    finally:
        ReceiptFields._aliases = {}


def test_postprocess_alias_no_match():
    """ReceiptFields without matching alias leaves merchant unchanged."""
    ReceiptFields._aliases = {"CVS": "CVS Pharmacy"}
    try:
        fields = ReceiptFields(
            {"merchant": "Starbucks", "date": "2024-01-15", "total": "$42.50"}
        )
        assert fields["merchant"] == "Starbucks"
    finally:
        ReceiptFields._aliases = {}


# --- pin / unpin tests ---


def test_pin_adds_names(runner, vault):
    """Pin via args creates the pinned JSON file."""
    _write_md(vault, "receipts/test.md", _make_fm("Starbucks"))

    result = runner.invoke(
        merchant, ["pin", "Starbucks", "Target"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "Pinned: Starbucks, Target" in result.output
    pinned = json.loads((vault / ".obagent/merchant-pinned.json").read_text())
    assert pinned == ["Starbucks", "Target"]


def test_pin_interactive(runner, vault):
    """Interactive pin uses checkbox prompt."""
    _write_md(vault, "receipts/a.md", _make_fm("Starbucks"))
    _write_md(vault, "receipts/b.md", _make_fm("Target"))

    with _mock_checkbox(["Starbucks", "Target"]):
        result = runner.invoke(merchant, ["pin"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "Pinned: Starbucks, Target" in result.output
    pinned = json.loads((vault / ".obagent/merchant-pinned.json").read_text())
    assert pinned == ["Starbucks", "Target"]


def test_pin_merges_with_existing(runner, vault):
    """Pinning new names preserves existing pinned names."""
    pinned_dir = vault / ".obagent"
    pinned_dir.mkdir(parents=True, exist_ok=True)
    (pinned_dir / "merchant-pinned.json").write_text(json.dumps(["Starbucks"]))

    result = runner.invoke(merchant, ["pin", "Target"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    pinned = json.loads((pinned_dir / "merchant-pinned.json").read_text())
    assert pinned == ["Starbucks", "Target"]


def test_unpin_removes_names(runner, vault):
    """Unpin via args removes names from the pinned list."""
    pinned_dir = vault / ".obagent"
    pinned_dir.mkdir(parents=True, exist_ok=True)
    (pinned_dir / "merchant-pinned.json").write_text(
        json.dumps(["Starbucks", "Target"])
    )

    result = runner.invoke(merchant, ["unpin", "Target"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "Unpinned: Target" in result.output
    pinned = json.loads((pinned_dir / "merchant-pinned.json").read_text())
    assert pinned == ["Starbucks"]


def test_unpin_interactive(runner, vault):
    """Interactive unpin uses checkbox prompt."""
    pinned_dir = vault / ".obagent"
    pinned_dir.mkdir(parents=True, exist_ok=True)
    (pinned_dir / "merchant-pinned.json").write_text(
        json.dumps(["Starbucks", "Target"])
    )

    with _mock_checkbox(["Target"]):
        result = runner.invoke(merchant, ["unpin"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "Unpinned: Target" in result.output
    pinned = json.loads((pinned_dir / "merchant-pinned.json").read_text())
    assert pinned == ["Starbucks"]


def test_rename_interactive_excludes_pinned(runner, vault):
    """Pinned merchant names are excluded from interactive rename candidates."""
    _write_md(vault, "receipts/a.md", _make_fm("Starbucks"))
    _write_md(vault, "receipts/b.md", _make_fm("Target"))
    pinned_dir = vault / ".obagent"
    pinned_dir.mkdir(parents=True, exist_ok=True)
    (pinned_dir / "merchant-pinned.json").write_text(json.dumps(["Starbucks"]))

    with (
        _mock_select("Target") as mock_sel,
        _mock_text("Target Corp"),
        _mock_confirm(None),
    ):
        result = runner.invoke(merchant, ["rename"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    # Verify Starbucks was not in the choices offered to select
    choices = mock_sel.call_args.kwargs["choices"]
    assert "Starbucks" not in choices
    assert "Target" in choices


def test_rename_interactive_excludes_alias_destinations(runner, vault):
    """Alias destination names are implicitly pinned and excluded from rename."""
    _write_md(vault, "receipts/a.md", _make_fm("Starbucks"))
    _write_md(vault, "receipts/b.md", _make_fm("Target"))
    aliases_dir = vault / ".obagent"
    aliases_dir.mkdir(parents=True, exist_ok=True)
    (aliases_dir / "merchant-aliases.json").write_text(
        json.dumps({"SBUX": "Starbucks"})
    )

    with (
        _mock_select("Target") as mock_sel,
        _mock_text("Target Corp"),
        _mock_confirm(None),
    ):
        result = runner.invoke(merchant, ["rename"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    choices = mock_sel.call_args.kwargs["choices"]
    assert "Starbucks" not in choices
    assert "Target" in choices


# --- auto-rename tests ---

AUTO_RENAME_OPTS = ["auto-rename", "--openai-api-key", "test-key"]


def _mock_llm_response(mapping: dict):
    """Return a mock OpenAI client that returns the given JSON mapping."""
    content = json.dumps(mapping)
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


def _patch_openai(mock_client):
    return patch("openai.OpenAI", return_value=mock_client)


def test_auto_rename_accepts_all(runner, vault):
    """Auto-rename applies all accepted suggestions."""
    md1 = _write_md(vault, "receipts/a.md", _make_fm("STARBUCKS #1234"))
    md2 = _write_md(vault, "receipts/b.md", _make_fm("Starbucks"))

    llm = _mock_llm_response({"STARBUCKS #1234": "Starbucks"})
    with (
        _patch_openai(llm),
        _mock_checkbox(["STARBUCKS #1234 → Starbucks"]),
        _mock_confirm(True),
    ):
        result = runner.invoke(merchant, AUTO_RENAME_OPTS, obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    assert "merchant: Starbucks" in md1.read_text()
    assert "merchant: Starbucks" in md2.read_text()
    aliases = json.loads((vault / ".obagent/merchant-aliases.json").read_text())
    assert aliases == {"STARBUCKS #1234": "Starbucks"}


def test_auto_rename_accepts_none(runner, vault):
    """Selecting nothing does not modify files."""
    _write_md(vault, "receipts/a.md", _make_fm("STARBUCKS #1234"))
    _write_md(vault, "receipts/b.md", _make_fm("Starbucks"))

    llm = _mock_llm_response({"STARBUCKS #1234": "Starbucks"})
    with _patch_openai(llm), _mock_checkbox([]):
        result = runner.invoke(merchant, AUTO_RENAME_OPTS, obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "No renames selected" in result.output


def test_auto_rename_no_duplicates(runner, vault):
    """When LLM returns empty mapping, report no duplicates."""
    _write_md(vault, "receipts/a.md", _make_fm("Starbucks"))

    llm = _mock_llm_response({})
    with _patch_openai(llm):
        result = runner.invoke(merchant, AUTO_RENAME_OPTS, obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "No duplicates found" in result.output


def test_auto_rename_filters_pinned_from_rename(runner, vault):
    """Pinned names are not in the 'from' side of the mapping."""
    _write_md(vault, "receipts/a.md", _make_fm("Starbucks"))
    _write_md(vault, "receipts/b.md", _make_fm("SBUX"))
    pinned_dir = vault / ".obagent"
    pinned_dir.mkdir(parents=True, exist_ok=True)
    (pinned_dir / "merchant-pinned.json").write_text(json.dumps(["Starbucks"]))

    # LLM suggests renaming both ways but pinned should be filtered
    llm = _mock_llm_response({"Starbucks": "SBUX", "SBUX": "Starbucks"})
    with (
        _patch_openai(llm),
        _mock_checkbox(["SBUX → Starbucks"]),
        _mock_confirm(False),
    ):
        result = runner.invoke(merchant, AUTO_RENAME_OPTS, obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output


def test_auto_rename_decline_save(runner, vault):
    """Declining save does not create the aliases file."""
    _write_md(vault, "receipts/a.md", _make_fm("STARBUCKS #1234"))
    _write_md(vault, "receipts/b.md", _make_fm("Starbucks"))

    llm = _mock_llm_response({"STARBUCKS #1234": "Starbucks"})
    with (
        _patch_openai(llm),
        _mock_checkbox(["STARBUCKS #1234 → Starbucks"]),
        _mock_confirm(False),
    ):
        result = runner.invoke(merchant, AUTO_RENAME_OPTS, obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert not (vault / ".obagent/merchant-aliases.json").exists()


def test_auto_rename_no_names(runner, vault):
    """When vault has no merchant names, report early."""
    result = runner.invoke(merchant, AUTO_RENAME_OPTS, obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "No merchant names found" in result.output


def test_auto_rename_strips_markdown_fences(runner, vault):
    """LLM response wrapped in ```json fences is handled."""
    md = _write_md(vault, "receipts/a.md", _make_fm("STARBUCKS #1234"))
    _write_md(vault, "receipts/b.md", _make_fm("Starbucks"))

    # Simulate LLM wrapping response in markdown fences
    content = '```json\n{"STARBUCKS #1234": "Starbucks"}\n```'
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with (
        _patch_openai(mock_client),
        _mock_checkbox(["STARBUCKS #1234 → Starbucks"]),
        _mock_confirm(False),
    ):
        result = runner.invoke(merchant, AUTO_RENAME_OPTS, obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    assert "merchant: Starbucks" in md.read_text()
