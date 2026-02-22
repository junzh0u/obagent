# Install obagent CLI and zsh completions
install:
    uv tool install . --compile-bytecode --force
    _OBAGENT_COMPLETE=zsh_source obagent > ~/.dotfiles/.config/zsh/completions/_obagent
    @echo "Installed. Restart your shell to enable completions."

# Uninstall obagent CLI and zsh completions
uninstall:
    uv tool uninstall obagent
    rm -f ~/.dotfiles/.config/zsh/completions/_obagent
    @echo "Uninstalled. Restart your shell to clear completions."
