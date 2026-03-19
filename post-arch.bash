#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()    { echo -e "${GREEN}[+]${NC} $1"; }
warn()   { echo -e "${YELLOW}[!]${NC} $1"; }
error()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

log "Configuring pacman..."
sudo sed -i 's/^#ParallelDownloads.*/ParallelDownloads = 10/' /etc/pacman.conf
sudo sed -i 's/^#Color/Color/' /etc/pacman.conf

log "Updating system..."
sudo pacman -Syu --noconfirm

log "Installing git..."
sudo pacman -S --noconfirm --needed git

if ! command -v yay &>/dev/null; then
    log "Installing yay..."
    sudo pacman -S --noconfirm --needed base-devel
    git clone https://aur.archlinux.org/yay.git /tmp/yay
    (cd /tmp/yay && makepkg -si --noconfirm)
    rm -rf /tmp/yay
else
    warn "yay is already installed, skipping."
fi

PACMAN_PACKAGES=(
    ufw
    firefox
    eza
    starship
    fastfetch
    btop
    neovim
    yazi
    hwinfo
    expac
    which
    xdg-user-dirs
    kitty
)

FAILED_PACKAGES=()

log "Installing packages..."
for pkg in "${PACMAN_PACKAGES[@]}"; do
    if ! sudo pacman -S --noconfirm --needed "$pkg"; then
        warn "Failed to install: $pkg"
        FAILED_PACKAGES+=("$pkg")
    fi
done

if [ ${#FAILED_PACKAGES[@]} -gt 0 ]; then
    warn "The following packages failed to install: ${FAILED_PACKAGES[*]}"
fi

AUR_PACKAGES=(
    ttf-jetbrains-mono-nerd
)

FAILED_AUR_PACKAGES=()

log "Installing AUR packages..."
for pkg in "${AUR_PACKAGES[@]}"; do
    if ! yay -S --noconfirm --needed "$pkg"; then
        warn "Failed to install AUR package: $pkg"
        FAILED_AUR_PACKAGES+=("$pkg")
    fi
done

if [ ${#FAILED_AUR_PACKAGES[@]} -gt 0 ]; then
    warn "The following AUR packages failed to install: ${FAILED_AUR_PACKAGES[*]}"
fi

log "Creating filesystem..."
mkdir -p \
    ~/Desktop \
    ~/Audio \
    ~/Documents \
    ~/Downloads \
    ~/Pictures \
    ~/Videos \
    ~/Templates \
    ~/Public \
    ~/Projects \
    ~/src \
    ~/.local/bin \
    ~/.ssh \
    ~/.gnupg

chmod 700 ~/.ssh ~/.gnupg

mkdir -p ~/.config
cat > ~/.config/user-dirs.dirs << EOF
XDG_DESKTOP_DIR="$HOME/Desktop"
XDG_DOCUMENTS_DIR="$HOME/Documents"
XDG_DOWNLOAD_DIR="$HOME/Downloads"
XDG_MUSIC_DIR="$HOME/Audio"
XDG_PICTURES_DIR="$HOME/Pictures"
XDG_VIDEOS_DIR="$HOME/Videos"
XDG_TEMPLATES_DIR="$HOME/Templates"
XDG_PUBLICSHARE_DIR="$HOME/Public"
EOF

xdg-user-dirs-update

log "Configuring git..."
git config --global user.name "Obbaron"
git config --global user.email "ronbelina@gmail.com"
git config --global init.defaultBranch main
git config --global core.editor nvim

log "Cloning dotfiles..."
git clone https://github.com/Obbaron/dotfiles-et-al.git ~/src/dotfiles-et-al

log "Creating symlinks..."
ln -sf ~/src/dotfiles-et-al/.bashrc ~/.bashrc
ln -sf ~/src/dotfiles-et-al/nvim ~/.config/nvim
ln -sf ~/src/dotfiles-et-al/starship.toml ~/.config/starship.toml

log "Enabling UFW firewall..."
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable --force
sudo systemctl enable ufw

log "Done! Reboot to apply all changes."
