from commands.pipeline import Pipeline
from constants import TITLE_UNSAFE_CHARS


class DocumentPipeline(Pipeline):
    @property
    def name(self) -> str:
        return "document"

    def prompt(self, path: str, ocr_text: str) -> str:
        return (
            "I will provide you with the content of a document that has been "
            "partially read by OCR (so it may contain errors).\n"
            f'The document is stored under the path "{path}".\n'
            "Extract the following fields:\n"
            "- title: a concise, descriptive document title that captures the "
            "key subject and the sender or organization (do not just copy a "
            "heading from the document; synthesize a title that would help "
            "someone identify this document at a glance; use only plain text "
            "with no special characters like #, [, ], ^, |, /, or :)\n"
            "- date: the document date in YYYY-MM-DD format\n"
            "- summary: a 1-2 sentence summary of the document\n"
            "Respond ONLY with a JSON object containing these three fields, "
            "no additional text!\n\n" + ocr_text[:4000]
        )

    @property
    def field_defaults(self) -> dict[str, str]:
        return {"date": "", "summary": ""}

    def make_title(self, fields: dict[str, str]) -> str:
        parts = [p for p in (fields.get("date"), fields.get("title")) if p]
        title = " - ".join(parts)
        return "".join(c for c in title if c not in TITLE_UNSAFE_CHARS).strip()

    def format_frontmatter(self, fields: dict[str, str]) -> str:
        title = fields.get("title", "")
        date = fields.get("date", "")
        return f"---\ntitle: {title}\ndate: {date}\n---\n"

    def format_body(self, fields: dict[str, str]) -> str:
        summary = fields.get("summary", "")
        if not summary:
            return ""
        return f"> [!summary]\n> {summary}\n\n"


document_pipeline = DocumentPipeline()
