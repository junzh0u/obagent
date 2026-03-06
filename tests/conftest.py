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
    """Set up a mock Mistral client with OCR response and context manager support."""
    mock_client = MagicMock()
    mock_client.ocr.process.return_value = mock_ocr_response()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_mistral_cls.return_value = mock_client
    return mock_client


def setup_mock_openai(mock_openai_cls, **kwargs):
    """Set up a mock OpenAI client with chat response and context manager support."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_chat_response(**kwargs)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_openai_cls.return_value = mock_client
    return mock_client


def mock_chat_response_bs(
    bank_name="Chase",
    date="2024-01-01",
    end_date="2024-01-31",
    account_name="Checking",
    account_number="1234",
):
    """Create a mock OpenAI chat completion response for bank statement extraction."""
    content = json.dumps(
        {
            "bank_name": bank_name,
            "date": date,
            "end_date": end_date,
            "account_name": account_name,
            "account_number": account_number,
        }
    )
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def setup_mock_openai_bs(mock_openai_cls, **kwargs):
    """Set up a mock OpenAI client with BS chat response and context manager support."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_chat_response_bs(**kwargs)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_openai_cls.return_value = mock_client
    return mock_client


def mock_chat_response_doc(
    title="Tax Return 2024",
    date="2024-04-15",
    tags="finance, tax",
    people="",
    summary="Annual federal tax return filing.",
):
    """Create a mock OpenAI chat completion response for document extraction."""
    content = json.dumps(
        {"title": title, "date": date, "tags": tags, "people": people, "summary": summary}
    )
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def setup_mock_openai_doc(mock_openai_cls, **kwargs):
    """Set up a mock OpenAI client with doc chat response and context manager support."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_chat_response_doc(**kwargs)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_openai_cls.return_value = mock_client
    return mock_client
