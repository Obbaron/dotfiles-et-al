#!/bin/sh
# bootstrap.sh
#   1. installs dependencies: python >= 3.11 and git
#   2. obtains the project's root files: uses local copies beside this script
#      if present (repo re-run), else fetches them (pinned to REF) into a tmp dir
#   3. hands off to configure.py, telling it whether that dir is disposable
#
# Usage:
#   ./bootstrap.sh [ARGS...]      ARGS pass through to configure.py
# Config (read from env; override for testing):
#   REF       git ref to fetch/clone (default: tag)
#   REPO      owner/name on the forge
#   REPO_URL  git clone URL (handed to configure.py)
#   RAW_URL   base URL for raw file fetches
#   DRY_RUN   report actions but does nothing

set -eu

REF="${REF:-v1.0.0}"
REPO="${REPO:-Obbaron/dotfiles-et-al}"
REPO_URL="${REPO_URL:-https://github.com/$REPO.git}"
RAW_URL="${RAW_URL:-https://raw.githubusercontent.com/$REPO/$REF}"
ROOT_FILES="configure.py config.toml install-pkg.sh"
MIN_PY_MAJOR=3
MIN_PY_MINOR=11
DRY_RUN="${DRY_RUN:-}"

say() { printf '[bootstrap] %s\n' "$*" >&2; }
die() { printf '[bootstrap] error: %s\n' "$*" >&2; exit 1; }

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

# pick a downloader once; hide the curl/wget difference (esp. 404 handling)
set_fetch() {
    if command -v curl >/dev/null 2>&1; then
        fetch() { curl -fsSL "$1" -o "$2"; }
    elif command -v wget >/dev/null 2>&1; then
        fetch() { wget -qO "$2" "$1"; }
    else
        die "need curl or wget to fetch project files"
    fi
}

# all three root files present in a directory?
have_root_files() {
    [ -e "$1/configure.py" ] && [ -e "$1/config.toml" ] && [ -e "$1/install-pkg.sh" ]
}

main() {
    local need py f mode

    # 1. dependencies: python (to run configure.py) and git (for its clone)
    need=""
    command -v git >/dev/null 2>&1 || need="$need git"
    py=""
    if py=$(find_python); then
        say "python ok: $py ($("$py" --version 2>&1))"
    else
        say "no python >= $MIN_PY_MAJOR.$MIN_PY_MINOR found; will install python3"
        need="$need python3"
    fi
    # shellcheck disable=SC2086
    [ -z "$need" ] || install_pkgs $need
    if [ -z "$py" ] && [ -z "$DRY_RUN" ]; then
        py=$(find_python) || die "python >= $MIN_PY_MAJOR.$MIN_PY_MINOR still unavailable after installing python3 — install a newer Python (backport/PPA) and re-run"
        say "python ok: $py ($("$py" --version 2>&1))"
    fi

    srcdir=""
    # shellcheck disable=SC1007
    if [ -f "$0" ] \
        && srcdir=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) \
        && have_root_files "$srcdir"; then
        mode="--keep"
        say "using local root files: $srcdir"
    else
        mode="--ephemeral"
        set_fetch
        srcdir=$(mktemp -d) || die "mktemp failed"
        trap 'rm -rf "$srcdir"' EXIT INT TERM
        say "fetching root files @ $REF -> $srcdir"
        # shellcheck disable=SC2086
        for f in $ROOT_FILES; do
            if [ -n "$DRY_RUN" ]; then
                say "+ fetch $RAW_URL/$f"
            else
                fetch "$RAW_URL/$f" "$srcdir/$f" || die "failed to fetch $f"
                [ -s "$srcdir/$f" ] || die "fetched empty file: $f"
            fi
        done
        
        [ -n "$DRY_RUN" ] || head -n1 "$srcdir/configure.py" | grep -q '^#\|^import\|^from\|^"""' \
            || die "configure.py does not look like Python — check REF / REPO"
    fi

    if [ -n "$DRY_RUN" ]; then
        say "dry run: would exec ${py:-python3} $srcdir/configure.py $srcdir $mode $REF $REPO_URL $*"
        return 0
    fi
    say "exec configure.py $*"
    exec "$py" "$srcdir/configure.py" "$srcdir" "$mode" "$REF" "$REPO_URL" "$@"
}

main "$@"
