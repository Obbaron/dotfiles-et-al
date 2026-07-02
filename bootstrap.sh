#!/bin/sh
# bootstrap.sh
#   1. ensures dependencies: git >= 2.25 and python >= 3.11
#   2. obtains the repo at REF ($REPO_HOME, under XDG data):
#      first run sparse-clones (root level only); a re-run fetches + checks out REF
#   3. hands off to configure.py passing through the user's args
#
# Usage:
#   ./bootstrap.sh <profile> [ARGS...]   ARGS pass through to configure.py
# Config:
#   REF        git tag (or ref) to clone/checkout
#   REPO       owner/name
#   REPO_URL   git clone URL
#   REPO_HOME  repo destination
#   DRY_RUN    report actions but change nothing

set -eu

REF="${REF:-v1.1.3}"
REPO="${REPO:-Obbaron/dotfiles-et-al}"
REPO_URL="${REPO_URL:-https://github.com/$REPO.git}"
REPO_HOME="${REPO_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/dotfiles-et-al}"
MIN_PY_MAJOR=3
MIN_PY_MINOR=11
MIN_GIT_MAJOR=2
MIN_GIT_MINOR=25
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

git_ok() {
    command -v git >/dev/null 2>&1 || return 1
    local v major minor
    v=$(git --version 2>/dev/null) || return 1
    v=${v#git version }                  # "2.39.3" / "2.39.3 (Apple Git-145)"
    major=${v%%.*}                       # "2"
    minor=${v#*.}; minor=${minor%%.*}    # "39"
    case "$major" in ''|*[!0-9]*) return 1 ;; esac
    case "$minor" in ''|*[!0-9]*) return 1 ;; esac
    [ "$major" -gt "$MIN_GIT_MAJOR" ] && return 0
    [ "$major" -eq "$MIN_GIT_MAJOR" ] && [ "$minor" -ge "$MIN_GIT_MINOR" ]
}

clone_repo() {
    say "cloning $REPO_URL @ $REF -> $REPO_HOME"
    if [ -n "$DRY_RUN" ]; then
        say "+ git -c advice.detachedHead=false clone --branch $REF --sparse $REPO_URL $REPO_HOME"
        return 0
    fi
    mkdir -p "$(dirname -- "$REPO_HOME")" || die "cannot create parent of $REPO_HOME"
    git -c advice.detachedHead=false clone --branch "$REF" --sparse "$REPO_URL" "$REPO_HOME" \
        || die "git clone failed (check REF=$REF / REPO_URL=$REPO_URL)"
}

update_repo() {
    say "updating repo @ $REF in $REPO_HOME"
    if [ -n "$DRY_RUN" ]; then
        say "+ git -C $REPO_HOME fetch --tags origin"
        say "+ git -C $REPO_HOME checkout [origin/]$REF"
        return 0
    fi
    git -C "$REPO_HOME" fetch --tags origin || die "git fetch failed in $REPO_HOME"
    # A branch ref must follow the remote: checking out the local branch would
    # pin us to whatever it pointed at last time. Detach at origin/REF instead.
    # Tags and raw SHAs have no origin/ counterpart and check out directly.
    if git -C "$REPO_HOME" rev-parse --verify --quiet "refs/remotes/origin/$REF" >/dev/null; then
        git -C "$REPO_HOME" -c advice.detachedHead=false checkout --detach "origin/$REF" \
            || die "git checkout origin/$REF failed (dirty tree? resolve and re-run)"
    else
        git -C "$REPO_HOME" -c advice.detachedHead=false checkout "$REF" \
            || die "git checkout $REF failed (dirty tree? resolve and re-run)"
    fi
}

main() {
    local need py

    need=""
    if git_ok; then
        say "git ok: $(git --version)"
    else
        say "git missing or < $MIN_GIT_MAJOR.$MIN_GIT_MINOR; will install git"
        need="$need git"
    fi
    py=""
    if py=$(find_python); then
        say "python ok: $py ($("$py" --version 2>&1))"
    else
        say "no python >= $MIN_PY_MAJOR.$MIN_PY_MINOR found; will install python3"
        need="$need python3"
    fi

    # shellcheck disable=SC2086
    [ -z "$need" ] || install_pkgs $need

    if [ -z "$DRY_RUN" ]; then
        git_ok || die "git >= $MIN_GIT_MAJOR.$MIN_GIT_MINOR still unavailable after install; install a newer git and re-run"
        if [ -z "$py" ]; then
            py=$(find_python) || die "python >= $MIN_PY_MAJOR.$MIN_PY_MINOR still unavailable after installing python3; install a newer Python (backport/PPA) and re-run"
            say "python ok: $py ($("$py" --version 2>&1))"
        fi
    fi

    if [ -d "$REPO_HOME/.git" ]; then
        update_repo
    elif [ -e "$REPO_HOME" ]; then
        die "$REPO_HOME exists but is not a git repo; remove it and re-run"
    else
        clone_repo
    fi

    if [ -n "$DRY_RUN" ]; then
        say "dry run: would exec ${py:-python3} $REPO_HOME/configure.py $*"
        return 0
    fi
    say "exec configure.py"
    exec "$py" "$REPO_HOME/configure.py" "$@"
}

main "$@"
