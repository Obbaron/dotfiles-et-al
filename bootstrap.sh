#!/bin/sh
#
# bootstrap.sh
#   1. installs dependenciest: python >= 3.11 and git
#   2. clones the project repo into the current directory
#   3. hands off to repo's configure.py
#
# Usage:
#   ./bootstrap.sh [ARGS...]      ARGS pass through to configure.py.
# Config:
#   REPO_URL    git repo URL
#   DRY_RUN     report actions but does nothing

set -eu

REPO_URL="${REPO_URL:-https://github.com/Obbaron/dotfiles-et-al.git}"
MIN_PY_MAJOR=3
MIN_PY_MINOR=11
DRY_RUN="${DRY_RUN:-}"

say() { printf '[bootstrap] %s\n' "$*" >&2; }
die() { printf '[bootstrap] error: %s\n' "$*" >&2; exit 1; }


run() {
    if [ -n "$DRY_RUN" ]; then printf '[bootstrap] + %s\n' "$*" >&2; return 0; fi
    "$@"
}

run_priv() {
    if [ -n "$DRY_RUN" ]; then printf '[bootstrap] + %s\n' "$*" >&2; return 0; fi
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else die "need root or sudo to run: $*"; fi
}

detect_pkg_mgr() {
    local pm
    for pm in apt-get dnf dnf5 yum pacman zypper apk emerge xbps-install; do
        command -v "$pm" >/dev/null 2>&1 && { printf '%s\n' "$pm"; return 0; }
    done
    return 1
}

install_pkgs() {
    [ "$#" -ge 1 ] || return 0
    local mgr
    mgr=$(detect_pkg_mgr) || die "no supported package manager found"
    say "installing via $mgr: $*"
    case "$mgr" in
        apt-get)
            run_priv env DEBIAN_FRONTEND=noninteractive apt-get update
            run_priv env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
        dnf|dnf5|yum) run_priv "$mgr" install -y "$@" ;;
        pacman)       run_priv pacman -Sy --noconfirm "$@" ;;
        zypper)       run_priv zypper --non-interactive install "$@" ;;
        apk)          run_priv apk add "$@" ;;
        emerge)       run_priv emerge "$@" ;;
        xbps-install) run_priv xbps-install -Sy "$@" ;;
        *)            die "unsupported manager: $mgr" ;;
    esac
}

find_python() {
    local py
    for py in python3.13 python3.12 python3.11 python3 python; do
        command -v "$py" >/dev/null 2>&1 || continue
        if "$py" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PY_MAJOR, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
            command -v "$py"
            return 0
        fi
    done
    return 1
}

main() {
    local need py repo_dir entry

    need=""
    command -v git >/dev/null 2>&1 || need="$need git"

    py=""
    if py=$(find_python); then
        say "python ok: $py ($("$py" --version 2>&1))"
    else
        say "no python >= $MIN_PY_MAJOR.$MIN_PY_MINOR found; will install python3"
        need="$need python3"
    fi

    [ -z "$need" ] || install_pkgs $need

    if [ -z "$py" ] && [ -z "$DRY_RUN" ]; then
        py=$(find_python) || die "python >= $MIN_PY_MAJOR.$MIN_PY_MINOR still unavailable after installing python3 — install a newer Python (backport/PPA) and re-run"
        say "python ok: $py ($("$py" --version 2>&1))"
    fi

    repo_dir=$(basename "$REPO_URL" .git)
    if [ -e "$repo_dir" ]; then
        say "repo dir already present: ./$repo_dir (skipping clone)"
    else
        say "cloning $REPO_URL -> ./$repo_dir"
        run git clone "$REPO_URL" "$repo_dir"
    fi

    entry="$repo_dir/configure.py"
    if [ -n "$DRY_RUN" ]; then
        say "dry run: would exec ${py:-python3} $entry $*"
        return 0
    fi
    [ -r "$entry" ] || die "python entry not found: $entry"
    say "handing off to $entry"
    cd "$repo_dir"
    exec "$py" configure.py "$@"
}

main "$@"
