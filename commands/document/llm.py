from commands.document.render import RENDER_CONFIG
from commands.llm import make_llm_command


def _postprocess(fields):
    """Clean up document fields after LLM extraction."""


def _prompt(path, ocr_text):
    """Build the LLM prompt for document field extraction."""
    return (
        "I will provide you with the content of a document that has been "
        "partially read by OCR (so it may contain errors).\n"
        f'The document is stored under the path "{path}".\n'
        "Extract the following fields:\n"
        "- title: a concise, descriptive document title that captures the "
        "key subject and the sender or organization (do not just copy a "
        "heading from the document; synthesize a title that would help "
        "someone identify this document at a glance; use only plain text "
        "with no special characters like #, [, ], ^, |, /, or :)\n"
        "- date: the document date in YYYY-MM-DD format\n"
        "- summary: a 1-2 sentence summary of the document\n"
        "Respond ONLY with a JSON object containing these three fields, "
        "no additional text!\n\n" + ocr_text[:4000]
    )


llm = make_llm_command(
    prompt_fn=_prompt,
    postprocess=_postprocess,
    render_config=RENDER_CONFIG,
    help_text="Extract metadata via LLM from OCR'd document entries.",
)
