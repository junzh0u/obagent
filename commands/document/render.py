from commands.render import make_render_command
from constants import TITLE_UNSAFE_CHARS

FIELD_DEFAULTS = {"date": "", "summary": ""}


def make_title(fields):
    """Build a filesystem-safe title from document metadata fields."""
    parts = [p for p in (fields.get("date"), fields.get("title")) if p]
    title = " - ".join(parts)
    return "".join(c for c in title if c not in TITLE_UNSAFE_CHARS).strip()


def format_frontmatter(fields):
    """Format document fields as YAML frontmatter."""
    title = fields.get("title", "")
    date = fields.get("date", "")
    return f"---\ntitle: {title}\ndate: {date}\n---\n"


def format_body(fields):
    """Format the summary as an Obsidian callout."""
    summary = fields.get("summary", "")
    if not summary:
        return ""
    return f"> [!summary]\n> {summary}\n\n"


RENDER_CONFIG = {
    "field_defaults": FIELD_DEFAULTS,
    "make_title": make_title,
    "format_frontmatter": format_frontmatter,
    "format_body": format_body,
}

render = make_render_command(
    **RENDER_CONFIG,
    help_text="Render Obsidian notes from LLM-extracted document metadata.",
)
