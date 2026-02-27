import re

from commands.llm import make_llm_command


def _postprocess(fields):
    """Clean up bank statement fields after LLM extraction."""
    bank = fields.get("bank_name", "")
    acct = fields.get("account_name", "")
    if bank and acct:
        cleaned = re.sub(rf"^{re.escape(bank)}\s+", "", acct, flags=re.IGNORECASE)
        if cleaned:
            fields["account_name"] = cleaned

    num = fields.get("account_number", "")
    digits = re.sub(r"\D", "", num)
    if digits:
        fields["account_number"] = digits[-4:]


def _prompt(path, ocr_text):
    """Build the LLM prompt for bank statement field extraction."""
    return (
        "I will provide you with the content of a document that has been "
        "partially read by OCR (so it may contain errors).\n"
        f'The document is stored under the path "{path}".\n'
        "Extract the following fields:\n"
        "- date: the statement start date in YYYY-MM-DD format\n"
        "- end_date: the statement end date in YYYY-MM-DD format "
        "(empty string if single-day or not applicable)\n"
        "- bank_name: the issuing bank name (short brand name in title case)\n"
        "- account_name: the account's product name WITHOUT the bank name prefix "
        '(e.g. "Total Checking" not "Chase Total Checking", '
        '"Sapphire Checking", "Blue Cash Preferred")\n'
        "- account_number: the last 4 digits of the account number only\n"
        "Respond ONLY with a JSON object containing these five fields, "
        "no additional text!\n\n" + ocr_text[:4000]
    )


llm = make_llm_command(
    prompt_fn=_prompt,
    postprocess=_postprocess,
    help_text="Extract metadata via LLM from OCR'd bank statement entries.",
)
