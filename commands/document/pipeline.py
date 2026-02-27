import re
from typing import Literal, override

from commands.fields import Fields
from commands.pipeline import Pipeline
from constants import TITLE_UNSAFE_CHARS

TAG_CHARS = re.compile(r"[^a-zA-Z0-9_/\-]")


class DocumentFields(Fields[Literal["title", "date", "tags", "summary"]]):
    @override
    def postprocess(self) -> None:
        tags = self.get("tags", "")
        raw = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        clean = [
            t for t in (TAG_CHARS.sub("", t) for t in raw) if t and not t.isdigit()
        ]
        self["tags"] = ",".join(clean)

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
        tags = self.get("tags", "")
        tag_list = tags.split(",") if tags else []
        tag_lines = "".join(f"\n  - {t}" for t in tag_list)
        return f"---\ntitle: {title}\ndate: {date}\ntags:{tag_lines}\n---\n"

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
            "- tags: a comma-separated list of 2-5 short lowercase tags for "
            "an Obsidian PKM vault (only letters, numbers, hyphens, "
            "underscores, and / are allowed; each tag must contain at least "
            'one non-numeric character; e.g. "finance, tax" or '
            '"medical, insurance, claim"); use broad category tags, not '
            "document-specific words; omit generic tags like \"document\" "
            "and year-only tags like \"2024\" or \"y2024\"\n"
            "- summary: a 1-2 sentence summary of the document\n"
            "Respond ONLY with a JSON object containing these four fields, "
            "no additional text!\n\n" + ocr_text[:4000]
        )


document_pipeline = DocumentPipeline()
