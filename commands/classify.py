from openai import OpenAI

from lib.constants import CLASSIFY_MODEL
from lib.pipeline import Pipeline


def classify_document(
    ocr_text: str,
    client: OpenAI,
    *,
    default_pipeline: Pipeline,
    model: str = CLASSIFY_MODEL,
    max_chars: int = 8000,
) -> Pipeline:
    """Ask the LLM which registered type a document is, from its OCR text.

    Returns the matching Pipeline (by ``default_path``); falls back to
    ``default_pipeline`` on empty OCR or an unrecognized answer. Only pipelines
    with a non-empty ``classify_description`` are offered as choices.
    """
    text = ocr_text.strip()
    if not text:
        return default_pipeline

    choices = [p for p in Pipeline._registry if p.classify_description]
    catalog = "\n".join(
        f"- {p.default_path}: {p.classify_description}" for p in choices
    )
    prompt = (
        "Classify the scanned document below into exactly ONE of these "
        "categories:\n"
        f"{catalog}\n\n"
        "Reply with ONLY the category name, exactly as written above.\n\n"
        f"Document text:\n{text[:max_chars]}"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = (response.choices[0].message.content or "").strip().lower()
    if not answer:  # empty is a substring of everything — guard the lenient match below
        return default_pipeline

    # Exact match first (we ask for a terse, exact reply), then a lenient
    # substring match to tolerate singular/plural or a slightly chatty answer.
    for p in choices:
        if answer == p.default_path.lower():
            return p
    for p in choices:
        name = p.default_path.lower()
        if name in answer or name.rstrip("s") in answer or answer in name:
            return p
    return default_pipeline
