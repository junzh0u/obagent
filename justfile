# Install obagent CLI and zsh completions
install:
    uv tool install . --compile-bytecode --force --reinstall
    _OBAGENT_COMPLETE=zsh_source obagent > ~/.dotfiles/.config/zsh/completions/_obagent
    @echo "Installed. Restart your shell to enable completions."

# Verify formatting, lint, and test
check:
    uv run ruff format --check .
    uv run ruff check .
    uv run pytest tests/ -v

# Auto-fix formatting and lint issues
fix:
    uv run ruff format .
    uv run ruff check --fix .

# Uninstall obagent CLI and zsh completions
uninstall:
    uv tool uninstall obagent
    rm -f ~/.dotfiles/.config/zsh/completions/_obagent
    @echo "Uninstalled. Restart your shell to clear completions."
