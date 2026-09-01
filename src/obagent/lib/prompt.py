"""Yes/no confirmation that honors the root ``-y/--yes`` flag and non-tty runs."""

import sys

import click
import questionary


def interactive() -> bool:
    """True when both stdin and stdout are terminals (someone can answer)."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def assume_yes() -> bool:
    """True when the root command was invoked with ``-y/--yes``."""
    ctx = click.get_current_context(silent=True)
    return bool(ctx is not None and (ctx.obj or {}).get("yes"))


def confirm(message: str, *, default: bool = False) -> bool:
    """Ask a yes/no question.

    ``-y`` answers yes without prompting. Off a terminal there is nobody to ask,
    so the default is taken instead of aborting (questionary raises on a
    non-tty stdin, which used to kill the command after its work was done).
    """
    if assume_yes():
        return True
    return _ask(message, default)


def _ask(message: str, default: bool) -> bool:
    if not interactive():
        return default
    # ask() returns None on ctrl-c; treat that as "no".
    return questionary.confirm(message, default=default).ask() is True
