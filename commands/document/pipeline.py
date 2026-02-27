from typing import Literal, override

from commands.fields import Fields
from commands.pipeline import Pipeline
from constants import TITLE_UNSAFE_CHARS


class DocumentFields(Fields[Literal["title", "date", "summary"]]):
    @override
    def apply_defaults(self) -> None:
        if not self.get("date"):
            self["date"] = ""
        if not self.get("summary"):
            self["summary"] = ""

    @override
    def make_title(self) -> str:
        parts = [p for p in (self.get("date"), self.get("title")) if p]
        title = " - ".join(parts)
        return "".join(c for c in title if c not in TITLE_UNSAFE_CHARS).strip()

    @override
    def format_frontmatter(self) -> str:
        # Exclude summary from frontmatter; it goes in the body callout
        title = self.get("title", "")
        date = self.get("date", "")
        return f"---\ntitle: {title}\ndate: {date}\n---\n"

    @override
    def format_body(self) -> str:
        summary = self.get("summary", "")
        if not summary:
            return ""
        return f"> [!summary]\n> {summary}\n\n"


class DocumentPipeline(Pipeline):
    fields_class = DocumentFields

    @property
    @override
    def name(self) -> str:
        return "document"

    @override
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


document_pipeline = DocumentPipeline()
