# ~/.bashrc.d/00-env.sh
export EDITOR="nvim"
export VISUAL="$EDITOR"
export PAGER="less"
export LESS="-R --mouse"
export LANG="en_GB.UTF-8"
export LC_ALL="en_GB.UTF-8"
export GPG_TTY=$(tty)
[ -d "$HOME/bin" ]        && export PATH="$HOME/bin:$PATH"
[ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH"
