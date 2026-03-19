#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()    { echo -e "${GREEN}[+]${NC} $1"; }
warn()   { echo -e "${YELLOW}[!]${NC} $1"; }
error()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

log "Setting theme to Breeze Dark..."
kwriteconfig6 --file kdeglobals --group General --key ColorScheme "BreezeDark"
kwriteconfig6 --file kdeglobals --group KDE --key LookAndFeelPackage "org.kde.breezedark.desktop"
plasma-apply-lookandfeel --apply "org.kde.breezedark.desktop"

log "Installing Krohnkite..."
yay -S --noconfirm --needed kwin-scripts-krohnkite

log "Disabling splash screen..."
kwriteconfig6 --file ksplashrc --group KSplash --key Engine "none"
kwriteconfig6 --file ksplashrc --group KSplash --key Theme "none"

log "Done! Reboot or log out to apply all changes."
