from commands.render import make_render_command

FIELD_DEFAULTS = {"date": "", "total": "$0.00"}


def make_title(fields):
    """Build a filesystem-safe title from receipt metadata fields."""
    total = fields.get("total") or "$0.00"
    parts = [p for p in (fields.get("date"), fields.get("merchant"), total) if p]
    title = " - ".join(parts)
    return "".join(c for c in title if c not in r'\/:*?"<>|').strip()


def format_frontmatter(fields):
    """Format receipt fields as YAML frontmatter."""
    merchant = fields.get("merchant", "")
    date = fields.get("date", "")
    total = fields.get("total", "$0.00")
    return f"---\nmerchant: {merchant}\ndate: {date}\ntotal: {total}\n---\n"


render = make_render_command(
    field_defaults=FIELD_DEFAULTS,
    make_title=make_title,
    format_frontmatter=format_frontmatter,
    help_text="Render Obsidian notes from LLM-extracted metadata.",
)
