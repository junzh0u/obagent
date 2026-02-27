import re

from commands.llm import make_llm_command
from commands.receipt.render import RENDER_CONFIG

_CURRENCY_SYMBOLS = {
    "$",
    "\u20ac",
    "\u00a3",
    "\u00a5",
    "\u20a9",
    "\u20b9",
    "\u20bd",
    "\u20ab",
    "\u20b1",
    "\u0e3f",
    "\u20ba",
    "\u20b4",
    "\u20b8",
    "\u20a6",
    "\u20b5",
}
_CURRENCY_CODE_RE = re.compile(
    r"[A-Z]{3}\$?\s*",  # e.g. "USD ", "USD$ ", "EUR "
)


def _clean_total(total):
    """Strip currency codes/names, keeping only the symbol and number.

    "USD$ 88.41" -> "$88.41", "$5.00 USD" -> "$5.00", "EUR 10.00" -> "\u20ac10.00"
    """
    code_to_symbol = {
        "USD": "$",
        "CAD": "$",
        "AUD": "$",
        "NZD": "$",
        "HKD": "$",
        "SGD": "$",
        "EUR": "\u20ac",
        "GBP": "\u00a3",
        "JPY": "\u00a5",
        "CNY": "\u00a5",
        "RMB": "\u00a5",
        "KRW": "\u20a9",
        "INR": "\u20b9",
        "RUB": "\u20bd",
        "VND": "\u20ab",
        "PHP": "\u20b1",
        "THB": "\u0e3f",
        "TRY": "\u20ba",
        "UAH": "\u20b4",
        "KZT": "\u20b8",
        "NGN": "\u20a6",
        "GHS": "\u20b5",
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


def _prompt(path, ocr_text):
    """Build the LLM prompt for receipt field extraction."""
    return (
        "I will provide you with the content of a document that has been "
        "partially read by OCR (so it may contain errors).\n"
        f'The document is stored under the path "{path}".\n'
        "Extract the following fields:\n"
        "- merchant: the merchant or vendor name (short brand name only in title case, "
        "preserve acronyms like CVS or IKEA, omit store numbers, locations, and addresses)\n"
        "- date: the document date in YYYY-MM-DD format\n"
        "- total: the total amount with currency symbol only, no currency code or name\n"
        "Respond ONLY with a JSON object containing these three fields, "
        "no additional text!\n\n" + ocr_text[:4000]
    )


def _postprocess(fields):
    """Clean up receipt-specific fields after LLM extraction."""
    if "total" in fields and fields["total"]:
        fields["total"] = _clean_total(fields["total"])


llm = make_llm_command(
    prompt_fn=_prompt,
    postprocess=_postprocess,
    render_config=RENDER_CONFIG,
    help_text="Extract metadata via LLM from OCR'd entries in the vault.",
)
