import re
from pathlib import Path
from typing import Literal, override

from lib.fields import Fields
from lib.pipeline import Pipeline
from lib.constants import TITLE_UNSAFE_CHARS

# Dollar currencies all render as "$" (indistinguishable, and Notion's Total is
# a $-typed number). Everything else uses its 3-letter ISO code so JPY vs CNY
# (both "\u00a5") stay distinct \u2014 this is the "Notion style" used by Non-USD Total.
_DOLLAR_CODES = {"USD", "CAD", "AUD", "NZD", "HKD", "SGD"}
_NON_DOLLAR_CODES = {
    "EUR",
    "GBP",
    "JPY",
    "CNY",
    "KRW",
    "INR",
    "RUB",
    "VND",
    "PHP",
    "THB",
    "TRY",
    "UAH",
    "KZT",
    "NGN",
    "GHS",
}
_CODE_ALIASES = {"RMB": "CNY"}
_ALL_CODES = _DOLLAR_CODES | _NON_DOLLAR_CODES | set(_CODE_ALIASES)
# Unambiguous symbol -> ISO code. "\u00a5" is intentionally absent (JPY vs CNY is
# ambiguous from the symbol alone; the LLM is prompted to emit the code).
_SYMBOL_TO_CODE = {
    "\u20ac": "EUR",
    "\u00a3": "GBP",
    "\u20a9": "KRW",
    "\u20b9": "INR",
    "\u20bd": "RUB",
    "\u20ab": "VND",
    "\u20b1": "PHP",
    "\u0e3f": "THB",
    "\u20ba": "TRY",
    "\u20b4": "UAH",
    "\u20b8": "KZT",
    "\u20a6": "NGN",
    "\u20b5": "GHS",
}
_CURRENCY_SYMBOLS = {"$", "\u00a5"} | set(_SYMBOL_TO_CODE)
_CURRENCY_CODE_RE = re.compile(r"[A-Z]{3}\$?\s*")  # e.g. "USD ", "USD$ ", "EUR "


def _resolve_currency(token: str) -> str | None:
    """Map a currency code or symbol to "$", an ISO code, "\u00a5", or None."""
    code = _CODE_ALIASES.get(token.upper(), token.upper())
    if code in _DOLLAR_CODES:
        return "$"
    if code in _NON_DOLLAR_CODES:
        return code
    if token in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[token]
    if token in ("$", "\u00a5"):
        return token
    return None


def _clean_total(total: str) -> str:
    """Normalize a total to Notion style: "$<amt>" for dollars, "<ISO> <amt>" else.

    "USD$ 88.41" -> "$88.41", "$5.00 USD" -> "$5.00", "EUR 10.00" -> "EUR 10.00",
    "RMB 66.00" -> "CNY 66.00", "JPY 1200" -> "JPY 1200". A bare "\u00a51200" stays
    "\u00a51200" (JPY/CNY ambiguous from the symbol alone).
    """
    s = total.strip()
    if not s:
        return s

    currency: str | None = None
    amount = s
    # Trailing code: "$5.00 USD", "\u00a566.00 RMB"
    parts = s.rsplit(None, 1)
    if len(parts) == 2 and parts[1].upper() in _ALL_CODES:
        currency = _resolve_currency(parts[1])
        amount = parts[0]
    else:
        m = _CURRENCY_CODE_RE.match(s)
        if m:  # Leading code: "USD 5.00", "USD$ 88.41", "EUR 10.00"
            currency = _resolve_currency(m.group().rstrip("$ "))
            amount = s[m.end() :]
        elif s[0] in _CURRENCY_SYMBOLS:  # Leading symbol: "\u00a329.99", "\u00a51200"
            currency = _resolve_currency(s[0])
            amount = s[1:]

    if currency is None:
        return s
    amount = amount.strip()
    if amount and amount[0] in _CURRENCY_SYMBOLS:  # drop any leftover symbol
        amount = amount[1:].strip()
    if currency in ("$", "\u00a5"):
        return f"{currency}{amount}"
    return f"{currency} {amount}"


class ReceiptFields(Fields[Literal["merchant", "date", "total"]]):
    _aliases: dict[str, str] = {}

    @override
    def postprocess(self) -> None:
        merchant = self.get("merchant", "")
        if merchant and self._aliases:
            self["merchant"] = self._aliases.get(merchant, merchant)

        if "total" in self and self["total"]:
            self["total"] = _clean_total(self["total"])

    @override
    def apply_defaults(self) -> None:
        super().apply_defaults()
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

    @override
    def prepare_context(self, vault: Path) -> None:
        from commands.merchant import ALIASES_FILE
        from lib.name_store import load_json_dict

        ReceiptFields._aliases = load_json_dict(vault, ALIASES_FILE)

    @property
    @override
    def name(self) -> str:
        return "receipt"

    @property
    @override
    def default_path(self) -> str:
        return "Receipts"

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
            "- merchant: the merchant or vendor name (short brand name only in title case, "
            "preserve acronyms like CVS or IKEA, omit store numbers, locations, and addresses)\n"
            "- date: the document date in YYYY-MM-DD format\n"
            "- total: the total amount. Use a '$' prefix for dollar currencies "
            "(USD, CAD, AUD, etc.; e.g. '$5.00'); for any other currency use its "
            "3-letter ISO code, a space, then the amount "
            "(e.g. 'EUR 10.00', 'JPY 3775', 'CNY 163.50')\n"
            "Respond ONLY with a JSON object containing these three fields, "
            "no additional text!\n\n{ocr_text}"
        )


receipt_pipeline = ReceiptPipeline()
