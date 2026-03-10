import json
from unittest.mock import patch

from commands.bank import bank
from commands.bank_statement.pipeline import BankStatementFields


def _write_md(vault, rel_path, content):
    md = vault / rel_path
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(content)
    return md


FM_TEMPLATE = (
    "---\nbank_name: {bank_name}\ndate: 2024-01-01\n"
    "end_date: 2024-01-31\naccount_name: Checking\n"
    'account_number: "1234"\nconsumed_at: 2024-01-01\n---\n'
    "Body text\n"
)


def _make_fm(bank_name):
    return FM_TEMPLATE.format(bank_name=bank_name)


def _mock_confirm(answer):
    return patch(
        "commands.bank.questionary.confirm",
        return_value=type("Q", (), {"ask": staticmethod(lambda: answer)})(),
    )


def _mock_select(answer):
    return patch(
        "commands.bank.questionary.select",
        return_value=type("Q", (), {"ask": staticmethod(lambda: answer)})(),
    )


def _mock_text(answer):
    return patch(
        "commands.bank.questionary.text",
        return_value=type("Q", (), {"ask": staticmethod(lambda: answer)})(),
    )


def _mock_checkbox(answer):
    return patch(
        "commands.bank.questionary.checkbox",
        return_value=type("Q", (), {"ask": staticmethod(lambda: answer)})(),
    )


def test_rename_bank(runner, vault):
    """Basic rename updates the bank_name field."""
    md = _write_md(vault, "stmts/test.md", _make_fm("Chase"))

    with _mock_confirm(None):
        result = runner.invoke(
            bank, ["rename", "Chase", "JPMorgan"], obj={"vault": str(vault)}
        )

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    content = md.read_text()
    assert "bank_name: JPMorgan" in content
    assert "Chase" not in content


def test_rename_skips_unrelated(runner, vault):
    """Files without the old bank name are not modified."""
    md = _write_md(vault, "stmts/test.md", _make_fm("Wells Fargo"))

    result = runner.invoke(
        bank, ["rename", "Chase", "JPMorgan"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output
    assert md.read_text() == _make_fm("Wells Fargo")


def test_rename_no_frontmatter(runner, vault):
    """Files without frontmatter are skipped."""
    _write_md(vault, "stmts/test.md", "No frontmatter here.\n")

    result = runner.invoke(
        bank, ["rename", "Chase", "JPMorgan"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output


def test_rename_skips_assets(runner, vault):
    """Files inside _assets_ directories are skipped."""
    _write_md(vault, "stmts/_assets_/abc/src/test.md", _make_fm("Chase"))

    result = runner.invoke(
        bank, ["rename", "Chase", "JPMorgan"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output


def test_rename_multiple_files(runner, vault):
    """Rename updates across multiple files in different directories."""
    md1 = _write_md(vault, "stmts/a.md", _make_fm("Chase"))
    md2 = _write_md(vault, "other/b.md", _make_fm("Chase"))
    md3 = _write_md(vault, "stmts/c.md", _make_fm("Citi"))

    with _mock_confirm(None):
        result = runner.invoke(
            bank, ["rename", "Chase", "JPMorgan"], obj={"vault": str(vault)}
        )

    assert result.exit_code == 0
    assert "2 file(s) updated" in result.output
    assert "bank_name: JPMorgan" in md1.read_text()
    assert "bank_name: JPMorgan" in md2.read_text()
    assert "bank_name: Citi" in md3.read_text()


def test_rename_saves_to_aliases(runner, vault):
    """Confirming save writes the mapping to bank-aliases.json."""
    _write_md(vault, "stmts/test.md", _make_fm("Chase"))

    with _mock_confirm(True):
        runner.invoke(bank, ["rename", "Chase", "JPMorgan"], obj={"vault": str(vault)})

    aliases_path = vault / ".obagent/bank-aliases.json"
    assert aliases_path.exists()
    aliases = json.loads(aliases_path.read_text())
    assert aliases == {"Chase": "JPMorgan"}


def test_rename_declines_save(runner, vault):
    """Declining save does not create the aliases file."""
    _write_md(vault, "stmts/test.md", _make_fm("Chase"))

    with _mock_confirm(False):
        runner.invoke(bank, ["rename", "Chase", "JPMorgan"], obj={"vault": str(vault)})

    assert not (vault / ".obagent/bank-aliases.json").exists()


def test_rename_no_save_when_zero_updates(runner, vault):
    """No save prompt when nothing was updated."""
    _write_md(vault, "stmts/test.md", _make_fm("Wells Fargo"))

    result = runner.invoke(
        bank, ["rename", "Chase", "JPMorgan"], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output
    assert not (vault / ".obagent/bank-aliases.json").exists()


def test_rename_interactive(runner, vault):
    """Interactive mode uses select and text prompts."""
    _write_md(vault, "stmts/test.md", _make_fm("Chase"))

    with _mock_select("Chase"), _mock_text("JPMorgan"), _mock_confirm(None):
        result = runner.invoke(bank, ["rename"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output


def test_list_banks(runner, vault):
    """Lists unique bank names sorted."""
    _write_md(vault, "stmts/a.md", _make_fm("Wells Fargo"))
    _write_md(vault, "stmts/b.md", _make_fm("Chase"))
    _write_md(vault, "stmts/c.md", _make_fm("Chase"))

    result = runner.invoke(bank, ["list"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    lines = result.output.strip().split("\n")
    assert lines == ["Chase", "Wells Fargo"]


def test_remap_from_explicit_path(runner, vault, tmp_path):
    """Remap with an explicit JSON mapping file."""
    md = _write_md(vault, "stmts/test.md", _make_fm("Chase"))
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps({"Chase": "JPMorgan"}))

    result = runner.invoke(
        bank, ["remap", str(mapping_file)], obj={"vault": str(vault)}
    )

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    assert "bank_name: JPMorgan" in md.read_text()


def test_remap_from_default_path(runner, vault):
    """Remap from the default bank-aliases.json."""
    md = _write_md(vault, "stmts/test.md", _make_fm("Chase"))
    aliases_dir = vault / ".obagent"
    aliases_dir.mkdir(parents=True)
    (aliases_dir / "bank-aliases.json").write_text(json.dumps({"Chase": "JPMorgan"}))

    result = runner.invoke(bank, ["remap"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    assert "bank_name: JPMorgan" in md.read_text()


def test_remap_missing_file(runner, vault):
    """Error when no mapping file exists."""
    result = runner.invoke(bank, ["remap"], obj={"vault": str(vault)})

    assert result.exit_code != 0
    assert "Mapping file not found" in result.output


def test_remap_no_matches(runner, vault):
    """Zero updates when no bank names match the mapping."""
    _write_md(vault, "stmts/test.md", _make_fm("Wells Fargo"))
    aliases_dir = vault / ".obagent"
    aliases_dir.mkdir(parents=True)
    (aliases_dir / "bank-aliases.json").write_text(json.dumps({"Chase": "JPMorgan"}))

    result = runner.invoke(bank, ["remap"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "0 file(s) updated" in result.output


def test_save_merges_with_existing(runner, vault):
    """Saving merges new mapping with existing aliases."""
    _write_md(vault, "stmts/test.md", _make_fm("Chase"))
    aliases_dir = vault / ".obagent"
    aliases_dir.mkdir(parents=True)
    (aliases_dir / "bank-aliases.json").write_text(
        json.dumps({"BofA": "Bank of America"})
    )

    with _mock_confirm(True):
        runner.invoke(bank, ["rename", "Chase", "JPMorgan"], obj={"vault": str(vault)})

    aliases = json.loads((aliases_dir / "bank-aliases.json").read_text())
    assert aliases == {"BofA": "Bank of America", "Chase": "JPMorgan"}


def test_postprocess_applies_alias():
    """BankStatementFields with _aliases renames bank_name."""
    BankStatementFields._aliases = {"Chase": "JPMorgan"}
    try:
        fields = BankStatementFields(
            {
                "bank_name": "Chase",
                "date": "2024-01-01",
                "end_date": "",
                "account_name": "Checking",
                "account_number": "1234",
            }
        )
        assert fields["bank_name"] == "JPMorgan"
    finally:
        BankStatementFields._aliases = {}


def test_postprocess_alias_then_prefix_strip():
    """Alias resolves first, then prefix stripping uses the new name."""
    BankStatementFields._aliases = {"JPMorgan Chase": "Chase"}
    try:
        fields = BankStatementFields(
            {
                "bank_name": "JPMorgan Chase",
                "date": "2024-01-01",
                "end_date": "",
                "account_name": "Chase Sapphire",
                "account_number": "1234",
            }
        )
        assert fields["bank_name"] == "Chase"
        assert fields["account_name"] == "Sapphire"
    finally:
        BankStatementFields._aliases = {}


# --- pin / unpin tests ---


def test_pin_adds_names(runner, vault):
    """Pin via args creates the pinned JSON file."""
    _write_md(vault, "stmts/test.md", _make_fm("Chase"))

    result = runner.invoke(bank, ["pin", "Chase", "Citi"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "Pinned: Chase, Citi" in result.output
    pinned = json.loads((vault / ".obagent/bank-pinned.json").read_text())
    assert pinned == ["Chase", "Citi"]


def test_pin_interactive(runner, vault):
    """Interactive pin uses checkbox prompt."""
    _write_md(vault, "stmts/a.md", _make_fm("Chase"))
    _write_md(vault, "stmts/b.md", _make_fm("Citi"))

    with _mock_checkbox(["Chase", "Citi"]):
        result = runner.invoke(bank, ["pin"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "Pinned: Chase, Citi" in result.output
    pinned = json.loads((vault / ".obagent/bank-pinned.json").read_text())
    assert pinned == ["Chase", "Citi"]


def test_pin_merges_with_existing(runner, vault):
    """Pinning new names preserves existing pinned names."""
    pinned_dir = vault / ".obagent"
    pinned_dir.mkdir(parents=True)
    (pinned_dir / "bank-pinned.json").write_text(json.dumps(["Chase"]))

    result = runner.invoke(bank, ["pin", "Citi"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    pinned = json.loads((pinned_dir / "bank-pinned.json").read_text())
    assert pinned == ["Chase", "Citi"]


def test_unpin_removes_names(runner, vault):
    """Unpin via args removes names from the pinned list."""
    pinned_dir = vault / ".obagent"
    pinned_dir.mkdir(parents=True)
    (pinned_dir / "bank-pinned.json").write_text(json.dumps(["Chase", "Citi"]))

    result = runner.invoke(bank, ["unpin", "Citi"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "Unpinned: Citi" in result.output
    pinned = json.loads((pinned_dir / "bank-pinned.json").read_text())
    assert pinned == ["Chase"]


def test_unpin_interactive(runner, vault):
    """Interactive unpin uses checkbox prompt."""
    pinned_dir = vault / ".obagent"
    pinned_dir.mkdir(parents=True)
    (pinned_dir / "bank-pinned.json").write_text(json.dumps(["Chase", "Citi"]))

    with _mock_checkbox(["Citi"]):
        result = runner.invoke(bank, ["unpin"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "Unpinned: Citi" in result.output
    pinned = json.loads((pinned_dir / "bank-pinned.json").read_text())
    assert pinned == ["Chase"]


def test_rename_interactive_excludes_pinned(runner, vault):
    """Pinned bank names are excluded from interactive rename candidates."""
    _write_md(vault, "stmts/a.md", _make_fm("Chase"))
    _write_md(vault, "stmts/b.md", _make_fm("Citi"))
    pinned_dir = vault / ".obagent"
    pinned_dir.mkdir(parents=True)
    (pinned_dir / "bank-pinned.json").write_text(json.dumps(["Chase"]))

    with _mock_select("Citi") as mock_sel, _mock_text("Citibank"), _mock_confirm(None):
        result = runner.invoke(bank, ["rename"], obj={"vault": str(vault)})

    assert result.exit_code == 0
    assert "1 file(s) updated" in result.output
    # Verify Chase was not in the choices offered to select
    choices = mock_sel.call_args.kwargs["choices"]
    assert "Chase" not in choices
    assert "Citi" in choices
