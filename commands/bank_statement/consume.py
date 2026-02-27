from commands.bank_statement.llm import _postprocess, _prompt
from commands.bank_statement.render import RENDER_CONFIG
from commands.consume import make_consume_command

consume = make_consume_command(
    prompt_fn=_prompt,
    postprocess=_postprocess,
    render_config=RENDER_CONFIG,
    help_text="Consume bank statement files into the vault. Accepts files and/or directories.",
)
