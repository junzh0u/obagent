import re
from typing import Literal, override

from commands.fields import Fields
from commands.pipeline import Pipeline
from constants import TITLE_UNSAFE_CHARS


class BankStatementFields(
    Fields[Literal["bank_name", "date", "end_date", "account_name", "account_number"]],
):
    @override
    def postprocess(self) -> None:
        bank = self.get("bank_name", "")
        acct = self.get("account_name", "")
        if bank and acct:
            cleaned = re.sub(rf"^{re.escape(bank)}\s+", "", acct, flags=re.IGNORECASE)
            if cleaned:
                self["account_name"] = cleaned

        acct = self.get("account_name", "")
        if ":" in acct:
            stripped = acct[: acct.index(":")].strip()
            if stripped:
                self["account_name"] = stripped

        acct = self.get("account_name", "")
        stripped = re.sub(r"\s+Card$", "", acct, flags=re.IGNORECASE).strip()
        if stripped:
            self["account_name"] = stripped

        if not self.get("date") and self.get("end_date"):
            self["date"] = self.pop("end_date")

        num = self.get("account_number", "")
        digits = re.sub(r"\D", "", num)
        if digits:
            self["account_number"] = digits[-4:]

    @override
    def make_title(self) -> str:
        date = self.get("date")
        end_date = self.get("end_date")
        date_part = f"{date} to {end_date}" if date and end_date else date
        parts = [
            p
            for p in (
                date_part,
                self.get("bank_name"),
                self.get("account_name"),
                self.get("account_number"),
            )
            if p
        ]
        title = " - ".join(parts)
        return "".join(c for c in title if c not in TITLE_UNSAFE_CHARS).strip()


class BankStatementPipeline(Pipeline):
    fields_class = BankStatementFields

    @property
    @override
    def name(self) -> str:
        return "bank statement"

    @property
    @override
    def default_path(self) -> str:
        return "Bank Statements"

    @property
    @override
    def prompt_template(self) -> str:
        return (
            "I will provide you with the content of a document that has been "
            "partially read by OCR (so it may contain errors).\n"
            'The document is stored under the path "{path}".\n'
            "Extract the following fields:\n"
            "- date: the statement start date in YYYY-MM-DD format\n"
            "- end_date: the statement end date in YYYY-MM-DD format "
            "(empty string if single-day or not applicable)\n"
            "- bank_name: the issuing bank name (short brand name in title case)\n"
            "- account_name: the account's specific product name WITHOUT the bank name prefix, "
            'any sub-brand after a colon, or the generic word "Card". '
            "Prefer the actual product name over generic account types "
            '(e.g. "You Invest Trade" not "Brokerage", '
            '"Freedom" not "Chase Freedom: Ultimate Rewards", '
            '"Sapphire" not "Sapphire Card", '
            '"Blue Cash Preferred")\n'
            "- account_number: the last 4 digits of the account number only\n"
            "Respond ONLY with a JSON object containing these five fields, "
            "no additional text!\n\n{ocr_text}"
        )


bank_statement_pipeline = BankStatementPipeline()
