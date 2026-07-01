"""classify_document: OCR text → registered Pipeline (smart-inbox routing)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import commands.bank_statement.pipeline  # noqa: F401 — register pipelines
import commands.document.pipeline  # noqa: F401
import commands.receipt.pipeline  # noqa: F401

from commands.classify import classify_document
from commands.document.pipeline import document_pipeline


def _client(answer):
    """An OpenAI stub whose chat completion returns ``answer``."""
    resp = MagicMock()
    resp.choices = [SimpleNamespace(message=SimpleNamespace(content=answer))]
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    return client


def test_classifies_receipt():
    p = classify_document(
        "a receipt", _client("Receipts"), default_pipeline=document_pipeline
    )
    assert p.default_path == "Receipts"


def test_classifies_bank_statement():
    p = classify_document(
        "a statement", _client("Bank Statements"), default_pipeline=document_pipeline
    )
    assert p.default_path == "Bank Statements"


def test_singular_or_chatty_answer_still_matches():
    # tolerate "Receipt" (singular) and a slightly wordy reply
    assert (
        classify_document(
            "x", _client("Receipt"), default_pipeline=document_pipeline
        ).default_path
        == "Receipts"
    )
    assert (
        classify_document(
            "x",
            _client("This is a Bank Statement."),
            default_pipeline=document_pipeline,
        ).default_path
        == "Bank Statements"
    )


def test_unknown_answer_falls_back_to_default():
    p = classify_document(
        "x", _client("Spaceship blueprint"), default_pipeline=document_pipeline
    )
    assert p is document_pipeline


def test_empty_ocr_skips_the_llm_and_returns_default():
    client = _client("Receipts")
    p = classify_document("   \n  ", client, default_pipeline=document_pipeline)
    assert p is document_pipeline
    client.chat.completions.create.assert_not_called()  # no OCR text → no API call


def test_none_content_falls_back():
    p = classify_document("x", _client(None), default_pipeline=document_pipeline)
    assert p is document_pipeline
