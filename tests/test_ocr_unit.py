import hashlib
import json
from unittest.mock import patch

from commands.ocr import ocr
from constants import OCR_MODEL

from tests.conftest import setup_mock_mistral


@patch("commands.ocr.Mistral")
def test_ocr_results_saved_to_correct_paths(
    mock_mistral_cls, runner, vault, source_dir
):
    """OCR results are saved to ocr/ subdirectory with correct filenames."""
    setup_mock_mistral(mock_mistral_cls)

    content = b"ocr test content"
    sha = hashlib.sha256(content).hexdigest()
    target_dir = vault / "papers" / sha
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
    target_dir = vault / "papers" / sha
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
    target_dir = vault / "papers" / sha
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
    target_dir = vault / "papers" / sha
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
    target_dir = vault / "papers" / sha
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
def test_ocr_custom_model(mock_mistral_cls, runner, vault):
    """--ocr-model saves files under the custom model name and calls API with it."""
    mock_client = setup_mock_mistral(mock_mistral_cls)

    sha = "custom"
    target_dir = vault / "papers" / sha
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
