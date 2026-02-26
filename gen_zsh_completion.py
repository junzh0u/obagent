"""Generate a static zsh completion script from the Click command tree."""

import click

from main import cli


def _escape(text):
    return text.replace("'", "'\\''").replace("[", "\\[").replace("]", "\\]")


def _func_name(path):
    return "_" + "_".join(path).replace("-", "_")


def _emit_command(path, cmd, lines):
    fname = _func_name(path)
    is_group = isinstance(cmd, click.Group)

    args = []
    for param in cmd.params:
        if isinstance(param, click.Option):
            for opt in param.opts:
                desc = _escape(param.help or "")
                if param.is_flag:
                    args.append(f"        '{opt}[{desc}]'")
                elif isinstance(param.type, click.Path) and not param.type.file_okay:
                    args.append(
                        f"        '{opt}[{desc}]:{param.human_readable_name}:_directories'"
                    )
                else:
                    args.append(f"        '{opt}[{desc}]:{param.human_readable_name}:'")

    if is_group:
        subcmds = " ".join(sorted(cmd.commands))
        args.append(f"        '1:command:({subcmds})'")
        args.append("        '*::arg:->args'")

    for param in cmd.params:
        if isinstance(param, click.Argument):
            if param.nargs == -1:
                args.append("        '*:path:_files'")
            else:
                args.append(f"        ':{param.human_readable_name}:'")

    body = " \\\n".join(args)
    lines.append(f"{fname}() {{")
    if is_group:
        lines.append("    local -a line state")
    lines.append(f"    _arguments -C \\\n{body}")

    if is_group:
        lines.append("")
        lines.append("    case $state in")
        lines.append("        args)")
        lines.append("            case $line[1] in")
        for name, subcmd in sorted(cmd.commands.items()):
            child_fname = _func_name(path + [name])
            lines.append(f"                {name}) {child_fname} ;;")
        lines.append("            esac")
        lines.append("            ;;")
        lines.append("    esac")

    lines.append("}")
    lines.append("")

    if is_group:
        for name, subcmd in sorted(cmd.commands.items()):
            _emit_command(path + [name], subcmd, lines)


def generate():
    lines = ["#compdef obagent", ""]
    _emit_command(["obagent"], cli, lines)
    lines.append('_obagent "$@"')
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(generate(), end="")
