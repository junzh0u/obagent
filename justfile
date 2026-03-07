# Set up git hooks
setup:
    ln -sf ../../hooks/pre-commit .git/hooks/pre-commit
    @echo "Git hooks installed."

# Install obagent CLI and zsh completions
install:
    uv tool install . --compile-bytecode --force --reinstall
    uv run python gen_zsh_completion.py > ~/.dotfiles/.config/zsh/completions/_obagent
    @echo "Installed. Restart your shell to enable completions."

# Verify formatting, lint, and test
check:
    uv run ruff format --check .
    uv run ruff check .
    uv run ty check
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
