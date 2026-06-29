# Set up git hooks
setup:
    ln -sf ../../hooks/pre-commit .git/hooks/pre-commit
    @echo "Git hooks installed."

# Install obagent CLI and zsh completions
install:
    uv tool install . --compile-bytecode --force --reinstall
    mkdir -p ~/.local/share/zsh/site-functions
    uv run python gen_zsh_completion.py > ~/.local/share/zsh/site-functions/_obagent
    @echo "Installed. Restart your shell to enable completions."

# Run the obagent CLI (alias for `uv run obagent ...`)
run *ARGS:
    uv run obagent {{ARGS}}

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

# List all TODO/FIXME/HACK comments in the codebase
todo:
    @rg 'TODO|FIXME|HACK' --glob '*.py' -n --color always

# Uninstall obagent CLI and zsh completions
uninstall:
    uv tool uninstall obagent
    rm -f ~/.local/share/zsh/site-functions/_obagent
    @echo "Uninstalled. Restart your shell to clear completions."
