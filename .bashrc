#
# ~/.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

PS1='[\u@\h \W]\$ '

# Default colors
alias ls='ls --color=auto'
alias grep='grep --color=auto'

## Useful aliases
# Replace ls with eza
alias ls="eza -al --color=always --group-directories-first --icons"   # preferred listing
alias la="eza -a --color=always --group-directories-first --icons"    # all files and dirs
alias ll="eza -l --color=always --group-directories-first --icons"    # long format
alias lt="eza -at --color=always --group-directories-first --icons"   # tree listing
alias l.="eza -a | grep -e '^\.'"                                     # show only dotfiles

## Common use
alias b='btop'
alias ff='fastfetch'
alias c='clear'
alias q='exit'
alias config="$EDITOR ~/.bashrc"

alias grubup="sudo grub-mkconfig -o /boot/grub/grub.cfg"
alias fixpacman="sudo rm /var/lib/pacman/db.lck"
alias tarhow="tar -acf"
alias untar="tar -zxvf"
alias wget="wget -c"
alias psmem="ps auxf | sort -nr -k 4"
alias psmem10="ps auxf | sort -nr -k 4 | head -10"
alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."
alias ......="cd ../../../../.."
alias dir="dir --color=auto"
alias vdir="vdir --color=auto"
alias fgrep="fgrep --color=auto"
alias egrep="egrep --color=auto"
alias hw="hwinfo --short"                                              # Hardware Info
alias big="expac -H M '%m\t%n' | sort -h | nl"                        # Sort installed packages by size in MB
alias gitpkg="pacman -Q | grep -i '\-git' | wc -l"                    # Count -git packages
alias update="sudo pacman -Syu"

## Get fastest mirrors
alias mirror="sudo cachyos-rate-mirrors"

## Cleanup orphaned packages
alias cleanup="sudo pacman -Rns $(pacman -Qtdq)"

## Get the error messages from journalctl
alias jctl="journalctl -p 3 -xb"

## Recent installed packages
alias rip="expac --timefmt='%Y-%m-%d %T' '%l\t%n %v' | sort | tail -200 | nl"

## Yazi cd on exit
function y() {
	local tmp="$(mktemp -t "yazi-cwd.XXXXXX")" cwd
	command yazi "$@" --cwd-file="$tmp"
	IFS= read -r -d '' cwd < "$tmp"
	[ "$cwd" != "$PWD" ] && [ -d "$cwd" ] && builtin cd -- "$cwd"
	rm -f -- "$tmp"
}

## Starship profile
eval "$(starship init bash)"

fastfetch
