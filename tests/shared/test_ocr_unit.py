import hashlib
import json
from unittest.mock import MagicMock, patch

import httpx
from mistralai.client.errors import SDKError
from mistralai.client.models.ocrrequest import DocumentURLChunk, ImageURLChunk

from commands.ocr import _build_ocr_document, _ocr_with_retry
from commands.receipt.pipeline import receipt_pipeline
from constants import OCR_MODEL
from tests.conftest import setup_mock_mistral

ocr = receipt_pipeline.ocr_command


def _make_sdk_error(status_code):
    """Create an SDKError with the given status code."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = "error"
    response.headers = {}
    return SDKError("API error", response)


@patch("commands.ocr.Mistral")
def test_ocr_results_saved_to_correct_paths(
    mock_mistral_cls, runner, vault, source_dir
):
    """OCR results are saved to ocr/ subdirectory with correct filenames."""
    setup_mock_mistral(mock_mistral_cls)

    content = b"ocr test content"
    sha = hashlib.sha256(content).hexdigest()
    target_dir = vault / "papers" / "_assets_" / sha
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(content)

    result = runner.invoke(
        ocr,
        ["--mistral-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    ocr_dir = target_dir / "ocr"
    assert ocr_dir.exists()
    assert (ocr_dir / f"{OCR_MODEL}.json").exists()
    assert (ocr_dir / f"{OCR_MODEL}.txt").exists()


@patch("commands.ocr.Mistral")
def test_ocr_text_contains_concatenated_markdown(mock_mistral_cls, runner, vault):
    """OCR text file contains page markdowns separated by double newlines."""
    setup_mock_mistral(mock_mistral_cls)

    sha = "abc123"
    target_dir = vault / "papers" / "_assets_" / sha
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"ocr text test")

    runner.invoke(
        ocr,
        ["--mistral-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    txt = (target_dir / "ocr" / f"{OCR_MODEL}.txt").read_text()
    assert txt == "# Page 1\n\nHello world\n\n# Page 2\n\nGoodbye world"


@patch("commands.ocr.Mistral")
def test_ocr_json_contains_model_dump(mock_mistral_cls, runner, vault):
    """OCR JSON file contains valid JSON from model_dump()."""
    mock_client = setup_mock_mistral(mock_mistral_cls)
    mock_response = mock_client.ocr.process.return_value

    sha = "def456"
    target_dir = vault / "papers" / "_assets_" / sha
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"ocr json test")

    runner.invoke(
        ocr,
        ["--mistral-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    json_path = target_dir / "ocr" / f"{OCR_MODEL}.json"
    data = json.loads(json_path.read_text())
    assert data == mock_response.model_dump.return_value
    assert data["model"] == OCR_MODEL
    assert len(data["pages"]) == 2


@patch("commands.ocr.Mistral")
def test_ocr_skip_existing(mock_mistral_cls, runner, vault):
    """OCR is skipped when output already exists."""
    setup_mock_mistral(mock_mistral_cls)

    sha = "existing"
    target_dir = vault / "papers" / "_assets_" / sha
    ocr_dir = target_dir / "ocr"
    ocr_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")
    (ocr_dir / f"{OCR_MODEL}.txt").write_text("existing ocr text")

    result = runner.invoke(
        ocr,
        ["--mistral-api-key", "test-key"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "already exists, skipping" in result.output
    mock_mistral_cls.return_value.ocr.process.assert_not_called()
    assert (ocr_dir / f"{OCR_MODEL}.txt").read_text() == "existing ocr text"


@patch("commands.ocr.Mistral")
def test_ocr_overwrite_reruns(mock_mistral_cls, runner, vault):
    """With --overwrite, OCR is re-run even if output exists."""
    setup_mock_mistral(mock_mistral_cls)

    sha = "overwrite"
    target_dir = vault / "papers" / "_assets_" / sha
    ocr_dir = target_dir / "ocr"
    ocr_dir.mkdir(parents=True)
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"test")
    (ocr_dir / f"{OCR_MODEL}.txt").write_text("old ocr text")
    (ocr_dir / f"{OCR_MODEL}.json").write_text('{"old": true}')

    result = runner.invoke(
        ocr,
        ["--mistral-api-key", "test-key", "--overwrite"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "OCR completed" in result.output
    txt = (ocr_dir / f"{OCR_MODEL}.txt").read_text()
    assert "old ocr text" not in txt
    assert "# Page 1" in txt
    data = json.loads((ocr_dir / f"{OCR_MODEL}.json").read_text())
    assert "old" not in data


@patch("commands.ocr.Mistral")
def test_ocr_single_sha256(mock_mistral_cls, runner, vault):
    """When sha256 argument is given, only that entry is OCR'd."""
    setup_mock_mistral(mock_mistral_cls)

    target = vault / "papers" / "_assets_" / "target"
    (target / "src").mkdir(parents=True)
    (target / "src" / "original.pdf").write_bytes(b"target")

    other = vault / "papers" / "_assets_" / "other"
    (other / "src").mkdir(parents=True)
    (other / "src" / "original.pdf").write_bytes(b"other")

    result = runner.invoke(
        ocr,
        ["--mistral-api-key", "test-key", "target"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert (target / "ocr" / f"{OCR_MODEL}.txt").exists()
    assert not (other / "ocr").exists()


@patch("commands.ocr.Mistral")
def test_ocr_custom_model(mock_mistral_cls, runner, vault):
    """--ocr-model saves files under the custom model name and calls API with it."""
    mock_client = setup_mock_mistral(mock_mistral_cls)

    sha = "custom"
    target_dir = vault / "papers" / "_assets_" / sha
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.pdf").write_bytes(b"custom model test")

    result = runner.invoke(
        ocr,
        ["--mistral-api-key", "test-key", "--ocr-model", "custom-model"],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    ocr_dir = target_dir / "ocr"
    assert (ocr_dir / "custom-model.txt").exists()
    assert (ocr_dir / "custom-model.json").exists()
    call_kwargs = mock_client.ocr.process.call_args
    assert call_kwargs.kwargs["model"] == "custom-model"


@patch("commands.ocr.time.sleep")
def test_ocr_retries_on_429(mock_sleep):
    """_ocr_with_retry retries on 429 with exponential backoff."""
    client = MagicMock()
    success = MagicMock()
    client.ocr.process.side_effect = [
        _make_sdk_error(429),
        _make_sdk_error(429),
        success,
    ]

    result = _ocr_with_retry(
        client, "model", document=ImageURLChunk(image_url="test"), max_retries=3
    )

    assert result is success
    assert client.ocr.process.call_count == 3
    assert mock_sleep.call_args_list[0].args[0] == 2
    assert mock_sleep.call_args_list[1].args[0] == 4


@patch("commands.ocr.time.sleep")
def test_ocr_raises_after_max_retries(mock_sleep):
    """_ocr_with_retry raises after exhausting retries on 429."""
    client = MagicMock()
    client.ocr.process.side_effect = _make_sdk_error(429)

    try:
        _ocr_with_retry(
            client, "model", document=ImageURLChunk(image_url="test"), max_retries=2
        )
        assert False, "Should have raised"
    except SDKError:
        pass

    assert client.ocr.process.call_count == 3  # initial + 2 retries


@patch("commands.ocr.time.sleep")
def test_ocr_retries_on_5xx(mock_sleep):
    """_ocr_with_retry retries on any 5xx server error with exponential backoff."""
    for status in (500, 502, 503):
        mock_sleep.reset_mock()
        client = MagicMock()
        success = MagicMock()
        client.ocr.process.side_effect = [
            _make_sdk_error(status),
            success,
        ]

        result = _ocr_with_retry(
            client, "model", document=ImageURLChunk(image_url="test"), max_retries=3
        )

        assert result is success, f"Failed for status {status}"
        assert client.ocr.process.call_count == 2
        assert mock_sleep.call_args_list[0].args[0] == 2


@patch("commands.ocr.time.sleep")
def test_ocr_does_not_retry_non_retryable(mock_sleep):
    """_ocr_with_retry does not retry on non-retryable 4xx errors."""
    client = MagicMock()
    client.ocr.process.side_effect = _make_sdk_error(400)

    try:
        _ocr_with_retry(
            client, "model", document=ImageURLChunk(image_url="test"), max_retries=3
        )
        assert False, "Should have raised"
    except SDKError:
        pass

    assert client.ocr.process.call_count == 1
    mock_sleep.assert_not_called()


def test_build_ocr_document_pdf(tmp_path):
    """_build_ocr_document returns DocumentURLChunk for PDFs."""
    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(b"pdf content")
    doc = _build_ocr_document(pdf)
    assert isinstance(doc, DocumentURLChunk)
    assert doc.document_url.startswith("data:application/pdf;base64,")


def test_build_ocr_document_jpg(tmp_path):
    """_build_ocr_document returns ImageURLChunk for JPEGs."""
    jpg = tmp_path / "original.jpg"
    jpg.write_bytes(b"jpg content")
    doc = _build_ocr_document(jpg)
    assert isinstance(doc, ImageURLChunk)
    assert isinstance(doc.image_url, str)
    assert doc.image_url.startswith("data:image/jpeg;base64,")


def test_build_ocr_document_jpeg(tmp_path):
    """_build_ocr_document returns ImageURLChunk for .jpeg extension."""
    jpeg = tmp_path / "original.jpeg"
    jpeg.write_bytes(b"jpeg content")
    doc = _build_ocr_document(jpeg)
    assert isinstance(doc, ImageURLChunk)
    assert isinstance(doc.image_url, str)
    assert doc.image_url.startswith("data:image/jpeg;base64,")


@patch("commands.ocr.Mistral")
def test_ocr_jpeg_uses_image_url(mock_mistral_cls, runner, vault):
    """OCR on a JPEG source uses image_url API format."""
    mock_client = setup_mock_mistral(mock_mistral_cls)

    sha = "jpgsha"
    target_dir = vault / "papers" / "_assets_" / sha
    (target_dir / "src").mkdir(parents=True)
    (target_dir / "src" / "original.jpg").write_bytes(b"jpeg data")

    result = runner.invoke(
        ocr,
        ["--mistral-api-key", "test-key", sha],
        obj={"vault": str(vault), "path": "papers"},
    )

    assert result.exit_code == 0
    assert "OCR completed" in result.output
    call_kwargs = mock_client.ocr.process.call_args
    document = call_kwargs.kwargs["document"]
    assert isinstance(document, ImageURLChunk)
    assert isinstance(document.image_url, str)
    assert document.image_url.startswith("data:image/jpeg;base64,")
