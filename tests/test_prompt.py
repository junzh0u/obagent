from unittest.mock import patch

import click

from obagent.cli import cli
from obagent.lib import prompt


def _q(answer):
    """Patch questionary.confirm so .ask() returns *answer*."""
    return patch(
        "obagent.lib.prompt.questionary.confirm",
        return_value=type("Q", (), {"ask": staticmethod(lambda: answer)})(),
    )


def test_confirm_prompts_at_a_terminal():
    with patch("obagent.lib.prompt.interactive", return_value=True), _q(True) as q:
        assert prompt.confirm("Save?") is True
    q.assert_called_once_with("Save?", default=False)


def test_confirm_ctrl_c_is_no():
    with patch("obagent.lib.prompt.interactive", return_value=True), _q(None):
        assert prompt.confirm("Save?", default=True) is False


def test_confirm_takes_default_off_a_terminal():
    with patch("obagent.lib.prompt.interactive", return_value=False), _q(True) as q:
        assert prompt.confirm("Save?") is False
        assert prompt.confirm("Save?", default=True) is True
    q.assert_not_called()


def test_confirm_honors_root_yes_flag(runner):
    @click.command()
    @click.pass_context
    def cmd(ctx):
        ctx.obj = {"yes": True}
        click.echo(str(prompt.confirm("Save?")))

    with patch("obagent.lib.prompt.interactive", return_value=False), _q(False) as q:
        result = runner.invoke(cmd)
    assert result.output.strip() == "True"
    q.assert_not_called()


def test_yes_flag_saves_alias_without_a_tty(runner, vault):
    """`obagent -y merchant rename` persists the alias with no terminal attached."""
    md = vault / "Receipts" / "note.md"
    md.parent.mkdir()
    md.write_text("---\nmerchant: Cosmetic Boutique JDF\n---\n")
    args = ["--vault", str(vault), "merchant", "rename", "Cosmetic Boutique JDF", "X"]

    with patch("obagent.lib.prompt.interactive", return_value=False):
        result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert "merchant: X" in md.read_text()
    assert not (vault / ".obagent" / "merchant-aliases.json").exists()

    md.write_text("---\nmerchant: Cosmetic Boutique JDF\n---\n")
    with patch("obagent.lib.prompt.interactive", return_value=False):
        result = runner.invoke(cli, ["--vault", str(vault), "-y", *args[2:]])
    assert result.exit_code == 0, result.output
    aliases = (vault / ".obagent" / "merchant-aliases.json").read_text()
    assert '"Cosmetic Boutique JDF": "X"' in aliases
