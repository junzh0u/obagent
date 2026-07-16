from main import cli


def test_cli_rejects_non_vault_dir(runner, tmp_path):
    """A --vault dir with no .obagent/ marker anywhere above it is rejected."""
    d = tmp_path / "not-a-vault"
    d.mkdir()

    result = runner.invoke(cli, ["--vault", str(d), "check"])

    assert result.exit_code != 0
    assert "not an obagent vault" in result.output


def test_cli_accepts_vault_dir(runner, vault):
    result = runner.invoke(cli, ["--vault", str(vault), "check"])

    assert result.exit_code == 0
    assert "not an obagent vault" not in result.output


def test_cli_walks_up_to_vault_root(runner, vault):
    """Pointing --vault inside the vault (e.g. at Receipts/) resolves to the root."""
    sub = vault / "Receipts"
    sub.mkdir()

    result = runner.invoke(cli, ["--vault", str(sub), "check"])

    assert result.exit_code == 0
    assert "using vault root" in result.output
