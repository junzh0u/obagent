import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def vault(tmp_path):
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture
def source_dir(tmp_path):
    d = tmp_path / "source"
    d.mkdir()
    return d
