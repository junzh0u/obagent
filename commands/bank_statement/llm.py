from commands.llm import make_llm_command


def _prompt(path, ocr_text):
    """Build the LLM prompt for bank statement field extraction."""
    return (
        "I will provide you with the content of a document that has been "
        "partially read by OCR (so it may contain errors).\n"
        f'The document is stored under the path "{path}".\n'
        "Extract the following fields:\n"
        '- date_period: the statement period (e.g. "2024-01" or '
        '"2024-01-01 to 2024-01-31")\n'
        "- bank_name: the issuing bank name (short brand name in title case)\n"
        '- account_name: the account type (e.g. "Checking", "Savings", '
        '"Credit Card")\n'
        "- account_number: the last 4-5 digits of the account number only\n"
        "Respond ONLY with a JSON object containing these four fields, "
        "no additional text!\n\n" + ocr_text[:4000]
    )


llm = make_llm_command(
    prompt_fn=_prompt,
    postprocess=lambda fields: None,
    help_text="Extract metadata via LLM from OCR'd bank statement entries.",
)
