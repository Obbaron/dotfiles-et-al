# ~/.profile

# Source bashrc if running interactively
if [ -n "$BASH_VERSION" ] && [ -f "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi

# Env vars
export EDITOR="nvim"
export VISUAL="$EDITOR"
export PAGER="less"
export LESS="-R --mouse"
export LANG="en_GB.UTF-8"
export LC_ALL="en_GB.UTF-8"
export GPG_TTY=$(tty)

# Personal bin dirs
[ -d "$HOME/bin" ]        && export PATH="$HOME/bin:$PATH"
[ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH"

# Login greeting
fastfetch
