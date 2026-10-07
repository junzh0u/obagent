OCR_MODEL = "mistral-ocr-latest"
LLM_MODEL = "gpt-6-luna"
CLASSIFY_MODEL = (
    LLM_MODEL  # smart-inbox type classification (simple task; a cheaper model is fine)
)
AUTO_RENAME_MODEL = "gpt-6.1-sol"
ASSETS_DIR = "_assets_"
SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
TITLE_UNSAFE_CHARS = set(r'\/:*?"<>|#^[]')
