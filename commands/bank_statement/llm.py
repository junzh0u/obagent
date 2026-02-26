from commands.llm import make_llm_command


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
        "- account_name: the account's product name as shown on the statement "
        '(e.g. "Sapphire Checking", "Total Savings", "Blue Cash Preferred")\n'
        "- account_number: the last 4-5 digits of the account number only\n"
        "Respond ONLY with a JSON object containing these five fields, "
        "no additional text!\n\n" + ocr_text[:4000]
    )


llm = make_llm_command(
    prompt_fn=_prompt,
    postprocess=lambda fields: None,
    help_text="Extract metadata via LLM from OCR'd bank statement entries.",
)
