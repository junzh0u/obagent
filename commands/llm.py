import json
import re
from pathlib import Path

import click
from openai import OpenAI

from constants import ASSETS_DIR, LLM_MODEL
from utils import iter_entries, newest_file


_CURRENCY_SYMBOLS = {
    "$",
    "€",
    "£",
    "¥",
    "₩",
    "₹",
    "₽",
    "₫",
    "₱",
    "฿",
    "₺",
    "₴",
    "₸",
    "₦",
    "₵",
}
_CURRENCY_CODE_RE = re.compile(
    r"[A-Z]{3}\$?\s*",  # e.g. "USD ", "USD$ ", "EUR "
)


def _clean_total(total):
    """Strip currency codes/names, keeping only the symbol and number.

    "USD$ 88.41" -> "$88.41", "$5.00 USD" -> "$5.00", "EUR 10.00" -> "€10.00"
    """
    code_to_symbol = {
        "USD": "$",
        "CAD": "$",
        "AUD": "$",
        "NZD": "$",
        "HKD": "$",
        "SGD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
        "CNY": "¥",
        "RMB": "¥",
        "KRW": "₩",
        "INR": "₹",
        "RUB": "₽",
        "VND": "₫",
        "PHP": "₱",
        "THB": "฿",
        "TRY": "₺",
        "UAH": "₴",
        "KZT": "₸",
        "NGN": "₦",
        "GHS": "₵",
    }
    s = total.strip()
    # Extract leading currency code (e.g. "USD$ 88.41" or "EUR 10.00")
    m = _CURRENCY_CODE_RE.match(s)
    if m:
        code = m.group().rstrip("$ ")
        rest = s[m.end() :]
        # If the remainder already has a symbol, just return symbol + number
        if rest and rest[0] in _CURRENCY_SYMBOLS:
            return rest
        symbol = code_to_symbol.get(code, "$")
        return symbol + rest
    # Strip trailing currency code/name (e.g. "$5.00 USD")
    parts = s.rsplit(None, 1)
    if len(parts) == 2 and parts[1].upper() in code_to_symbol:
        return parts[0]
    return s


def extract_fields(target_dir, client, path, *, model=LLM_MODEL, overwrite=False):
    """Use OpenAI to extract metadata from OCR text and save as JSON.

    Discovers the newest OCR .txt file under target_dir/ocr/.
    If llm/<model>.json exists and not overwrite, skips and returns None.
    Returns the parsed fields dict on success, None if skipped.
    """
    llm_dir = target_dir / "llm"
    json_path = llm_dir / f"{model}.json"
    if json_path.exists() and not overwrite:
        click.secho("  LLM result already exists, skipping", fg="yellow")
        return None

    txt_path = newest_file(target_dir / "ocr", "*.txt")
    if txt_path is None:
        click.secho("  No OCR result found, skipping LLM", fg="yellow")
        return None
    ocr_text = txt_path.read_text()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    "I will provide you with the content of a document that has been "
                    "partially read by OCR (so it may contain errors).\n"
                    f'The document is stored under the path "{path}".\n'
                    "Extract the following fields:\n"
                    "- merchant: the merchant or vendor name (short brand name only in title case, "
                    "preserve acronyms like CVS or IKEA, omit store numbers, locations, and addresses)\n"
                    "- date: the document date in YYYY-MM-DD format\n"
                    "- total: the total amount with currency symbol only, no currency code or name "
                    '(e.g. "$5.00" not "$5.00 USD", "USD 5.00", or "USD$ 5.00")\n'
                    "Respond ONLY with a JSON object containing these three fields, "
                    "no additional text!\n\n" + ocr_text[:4000]
                ),
            },
        ],
    )
    raw = response.choices[0].message.content.strip()
    fields = json.loads(raw)
    if "total" in fields and fields["total"]:
        fields["total"] = _clean_total(fields["total"])
    llm_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(fields, indent=2) + "\n")
    click.secho(f"  Extracted: {fields}", fg="green")
    return fields


@click.command()
@click.option(
    "--openai-api-key",
    envvar="OPENAI_API_KEY",
    required=True,
    help="OpenAI API key for title extraction.",
)
@click.option(
    "--llm-model",
    default=LLM_MODEL,
    show_default=True,
    help="OpenAI model name for field extraction.",
)
@click.option("--overwrite", is_flag=True, help="Overwrite existing markdown files.")
@click.argument("sha256", required=False)
@click.pass_context
def llm(ctx, openai_api_key, llm_model, overwrite, sha256):
    """Extract metadata via LLM from OCR'd entries in the vault."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    if sha256:
        entries = [vault / path / ASSETS_DIR / sha256]
    else:
        entries = iter_entries(vault, path)
    with OpenAI(api_key=openai_api_key) as client:
        for target_dir in entries:
            click.secho(f"LLM: {target_dir}", bold=True)
            try:
                extract_fields(
                    target_dir,
                    client,
                    path,
                    model=llm_model,
                    overwrite=overwrite,
                )
            except Exception as e:
                click.secho(f"  Warning: field extraction failed: {e}", fg="red")
