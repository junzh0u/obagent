from commands.render import make_render_command

FIELD_DEFAULTS = {}


def make_safe_title(bank_name, date_period, account_name, account_number):
    """Build a filesystem-safe title from bank statement metadata fields."""
    parts = [p for p in (date_period, bank_name, account_name, account_number) if p]
    title = " - ".join(parts)
    return "".join(c for c in title if c not in r'\/:*?"<>|').strip()


def make_title(fields):
    """Build a title string from bank statement metadata fields."""
    return make_safe_title(
        fields.get("bank_name"),
        fields.get("date_period"),
        fields.get("account_name"),
        fields.get("account_number"),
    )


def format_frontmatter(fields):
    """Format bank statement fields as YAML frontmatter."""
    bank_name = fields.get("bank_name", "")
    date_period = fields.get("date_period", "")
    account_name = fields.get("account_name", "")
    account_number = fields.get("account_number", "")
    return (
        f"---\nbank_name: {bank_name}\ndate_period: {date_period}\n"
        f'account_name: {account_name}\naccount_number: "{account_number}"\n---\n'
    )


render = make_render_command(
    field_defaults=FIELD_DEFAULTS,
    make_title=make_title,
    format_frontmatter=format_frontmatter,
    help_text="Render Obsidian notes from LLM-extracted bank statement metadata.",
)
