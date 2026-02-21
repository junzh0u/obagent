import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from constants import OCR_MODEL

BOTH_KEYS = ["--mistral-api-key", "test-key", "--openai-api-key", "test-oai-key"]


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


def mock_ocr_response():
    """Create a mock OCR response with realistic structure."""
    page1 = SimpleNamespace(markdown="# Page 1\n\nHello world")
    page2 = SimpleNamespace(markdown="# Page 2\n\nGoodbye world")
    response = MagicMock()
    response.pages = [page1, page2]
    response.model_dump.return_value = {
        "pages": [
            {"markdown": "# Page 1\n\nHello world", "index": 0},
            {"markdown": "# Page 2\n\nGoodbye world", "index": 1},
        ],
        "model": OCR_MODEL,
    }
    return response


def mock_chat_response(merchant="ACME Store", date="2024-01-15", total="$42.50"):
    """Create a mock OpenAI chat completion response for metadata extraction."""
    content = json.dumps({"merchant": merchant, "date": date, "total": total})
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def setup_mock_mistral(mock_mistral_cls):
    """Set up a mock Mistral client with OCR response."""
    mock_client = MagicMock()
    mock_client.ocr.process.return_value = mock_ocr_response()
    mock_mistral_cls.return_value = mock_client
    return mock_client


def setup_mock_openai(mock_openai_cls, **kwargs):
    """Set up a mock OpenAI client with chat response."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_chat_response(**kwargs)
    mock_openai_cls.return_value = mock_client
    return mock_client
