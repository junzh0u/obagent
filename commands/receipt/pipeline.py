import re
from typing import Literal, override

from commands.fields import Fields
from commands.pipeline import Pipeline
from constants import TITLE_UNSAFE_CHARS

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


def _clean_total(total: str) -> str:
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


class ReceiptFields(Fields[Literal["merchant", "date", "total"]]):
    @override
    def postprocess(self) -> None:
        if "total" in self and self["total"]:
            self["total"] = _clean_total(self["total"])

    @override
    def apply_defaults(self) -> None:
        if not self.get("date"):
            self["date"] = ""
        if not self.get("total"):
            self["total"] = "$0.00"

    @override
    def make_title(self) -> str:
        parts = [
            p for p in (self.get("date"), self.get("merchant"), self.get("total")) if p
        ]
        title = " - ".join(parts)
        return "".join(c for c in title if c not in TITLE_UNSAFE_CHARS).strip()


class ReceiptPipeline(Pipeline):
    fields_class = ReceiptFields

    @property
    @override
    def name(self) -> str:
        return "receipt"

    @override
    def prompt(self, path: str, ocr_text: str) -> str:
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


receipt_pipeline = ReceiptPipeline()
