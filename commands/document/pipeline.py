import re
from pathlib import Path
from typing import Literal, override

from commands.fields import Fields
from commands.pipeline import Pipeline
from constants import TITLE_UNSAFE_CHARS
from utils import pinyin_sort_key

TAG_CHARS = re.compile(r"[^a-zA-Z0-9_/\-]")


class DocumentFields(Fields[Literal["title", "date", "tags", "people", "summary"]]):
    _aliases: dict[str, str] = {}

    @override
    def postprocess(self) -> None:
        tags = self.get("tags", "")
        raw = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        clean = [
            t for t in (TAG_CHARS.sub("", t) for t in raw) if t and not t.isdigit()
        ]
        self["tags"] = ",".join(clean)

        people = self.get("people", "")
        names = [p.strip() for p in people.split(",") if p.strip()] if people else []
        if self._aliases:
            from commands.people import _apply_mapping

            names = _apply_mapping(names, self._aliases)
        self["people"] = ",".join(names)

    @override
    def make_title(self) -> str:
        parts = [p for p in (self.get("date"), self.get("title")) if p]
        title = " - ".join(parts)
        return "".join(c for c in title if c not in TITLE_UNSAFE_CHARS).strip()

    @override
    def format_frontmatter(self, *, consumed_at: str = "") -> str:
        # Exclude summary from frontmatter; it goes in the body callout
        title = self.get("title", "")
        date = self.get("date", "")
        tags = self.get("tags", "")
        tag_list = sorted(tags.split(",")) if tags else []
        tag_lines = "".join(f"\n  - {t}" for t in tag_list)
        people = self.get("people", "")
        people_list = sorted(people.split(","), key=pinyin_sort_key) if people else []
        people_lines = "".join(f"\n  - {p}" for p in people_list)
        return (
            f"---\ntitle: {title}\ndate: {date}\ntags:{tag_lines}\n"
            f"people:{people_lines}\nconsumed_at: {consumed_at}\n---\n"
        )

    @override
    def format_body(self) -> str:
        summary = self.get("summary", "")
        if not summary:
            return ""
        return f"> [!summary]\n> {summary}\n\n"


class DocumentPipeline(Pipeline):
    fields_class = DocumentFields
    _known_names: list[str] = []

    @property
    @override
    def name(self) -> str:
        return "document"

    @property
    @override
    def default_path(self) -> str:
        return "Documents"

    @override
    def prepare_context(self, vault: Path) -> None:
        from commands.people import _collect_names, _load_aliases

        self._known_names = _collect_names(vault)
        DocumentFields._aliases = _load_aliases(vault)

    @override
    def prompt(self, path: str, ocr_text: str, filename: str = "") -> str:
        known_names_block = ""
        if self._known_names:
            joined = ", ".join(self._known_names)
            known_names_block = (
                f"Known people names in the vault: [{joined}]\n"
                "You MUST use the exact full name from this list when the "
                'person matches (e.g. if the list has "Zoey Zhou" and the '
                'document mentions "Zoey", output "Zoey Zhou"). '
                "Only introduce a new name if you are confident the person "
                "is not already on the list.\n"
            )
        return self.prompt_template.format(
            path=path,
            filename=filename,
            ocr_text=ocr_text[:4000],
            known_names=known_names_block,
        )

    @property
    @override
    def prompt_template(self) -> str:
        return (
            "I will provide you with the content of a document that has been "
            "partially read by OCR (so it may contain errors).\n"
            'The document is stored under the path "{path}".\n'
            'The original filename is "{filename}".\n'
            "The filename may contain useful hints, but prefer the document "
            "content when it provides clear information.\n"
            "Extract the following fields:\n"
            "- title: a concise, descriptive document title that captures the "
            "key subject and the sender or organization (do not just copy a "
            "heading from the document; synthesize a title that would help "
            "someone identify this document at a glance; use only plain text "
            "with no special characters like #, [, ], ^, |, /, or :)\n"
            "- date: the document date in YYYY-MM-DD format\n"
            "- tags: a comma-separated list of 3-10 short lowercase tags for "
            "an Obsidian PKM vault (only letters, numbers, hyphens, "
            "underscores, and / are allowed; each tag must contain at least "
            'one non-numeric character; e.g. "finance, tax" or '
            '"medical, insurance, claim"); use broad category tags, not '
            "document-specific words; include organization, company, or "
            "agency names as tags when relevant "
            '(e.g. "facebook", "uscis", "chase", "irs"); '
            "do not duplicate names already listed in people as tags; "
            'omit generic tags like "document" '
            'and year-only tags like "2024" or "y2024"\n'
            "{known_names}"
            "- people: a comma-separated list of people names relevant to the "
            "document (e.g. recipients, senders, account holders, signers); "
            'format each name as "First Last" in title case '
            '(e.g. "John Smith", not "SMITH, JOHN" or "john smith"); '
            "empty string if no specific people are mentioned\n"
            "- summary: a 1-2 sentence summary of the document\n"
            "Use the same language as the document text for title, summary, "
            "and people names.\n"
            "Respond ONLY with a JSON object containing these five fields, "
            "no additional text!\n\n{ocr_text}"
        )


document_pipeline = DocumentPipeline()
