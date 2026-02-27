from commands.consume import make_consume_command
from commands.receipt.llm import _postprocess, _prompt
from commands.receipt.render import RENDER_CONFIG

consume = make_consume_command(
    prompt_fn=_prompt,
    postprocess=_postprocess,
    render_config=RENDER_CONFIG,
    help_text="Consume receipt files into the vault. Accepts files and/or directories.",
)
