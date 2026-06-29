#!/bin/sh
# install-pkg.sh
set -eu

usage() {
    cat <<USAGE
Usage: install-pkg.sh [-h] [-n] [-t] [-l LEVEL] [-f MANIFEST] [PACKAGE...]

  -h            show help
  -n            dry run: print commands instead of running them
  -t            prefix log lines with UTC timestamp
  -l LEVEL      log level: debug|info|warn|error (default: info)
  -f MANIFEST   read package names from MANIFEST (one per line; # = comment)
  PACKAGE...    packages to install, in addition to any manifest
USAGE
}

DRY_RUN=""
TIMESTAMP=""
MANIFEST=""
LEVEL=info
MGR=""
ESC=$(printf '\033')


# Logging
_rank() { case "$1" in debug) echo 0 ;; info) echo 1 ;; warn) echo 2 ;; error) echo 3 ;; *) echo 1 ;; esac; }
log() {
    local lvl="$1"; shift
    [ "$(_rank "$lvl")" -ge "$(_rank "$LEVEL")" ] || return 0
    local ts="" color="" reset=""
    [ -n "$TIMESTAMP" ] && ts="$(date -u +%Y-%m-%dT%H:%M:%SZ) "
    if [ -z "${NO_COLOR:-}" ] && [ -t 2 ]; then
        case "$lvl" in
            debug) color="${ESC}[2m"  ;;
            info)  color="${ESC}[36m" ;;
            warn)  color="${ESC}[33m" ;;
            error) color="${ESC}[31m" ;;
        esac
        reset="${ESC}[0m"
    fi
    printf '%s%s%-5s%s %s\n' "$ts" "$color" "$lvl" "$reset" "$*" >&2
}
die() { log error "$*"; exit 1; }

# Packages
detect_mgr() {
    local mgr
    for mgr in apt-get dnf dnf5 yum pacman zypper apk emerge xbps-install; do
        command -v "$mgr" >/dev/null 2>&1 && { printf '%s\n' "$mgr"; return 0; }
    done
    return 1
}
run_priv() {
    if [ -n "$DRY_RUN" ]; then printf '+ %s\n' "$*" >&2; return 0; fi
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else die "need root or sudo to run: $*"; fi
}
refresh_index() {
    case "$MGR" in
        apt-get)      run_priv apt-get update ;;
        dnf|dnf5|yum) run_priv "$MGR" makecache ;;
        pacman)       run_priv pacman -Sy ;;
        zypper)       run_priv zypper refresh ;;
        apk)          run_priv apk update ;;
        emerge)       run_priv emerge --sync ;;
        xbps-install) run_priv xbps-install -S ;;
    esac
}
install_pkgs() {
    case "$MGR" in
        apt-get)      run_priv env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
        dnf|dnf5|yum) run_priv "$MGR" install -y "$@" ;;
        pacman)       run_priv pacman -S --noconfirm "$@" ;;
        zypper)       run_priv zypper --non-interactive install "$@" ;;
        apk)          run_priv apk add "$@" ;;
        emerge)       run_priv emerge "$@" ;;
        xbps-install) run_priv xbps-install -y "$@" ;;
    esac
}
is_installed() {
    case "$MGR" in
        apt-get)             dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'ok installed' ;;
        dnf|dnf5|yum|zypper) rpm -q "$1" >/dev/null 2>&1 ;;
        pacman)              pacman -Q "$1" >/dev/null 2>&1 ;;
        apk)                 apk info -e "$1" >/dev/null 2>&1 ;;
        emerge)              qlist -I -C "$1" >/dev/null 2>&1 ;;
        xbps-install)        xbps-query "$1" >/dev/null 2>&1 ;;
    esac
}

# Manifest
read_manifest() {
    [ -r "$1" ] || die "cannot read manifest: $1"
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in ''|\#*) continue ;; esac
        printf '%s\n' "$line"
    done < "$1"
    return 0
}


main() {
    local opt pkgs todo p
    while getopts ':hntl:f:' opt; do
        case "$opt" in
            h)  usage; exit 0 ;;
            n)  DRY_RUN=1 ;;
            t)  TIMESTAMP=1 ;;
            f)  MANIFEST=$OPTARG ;;
            l)  case "$OPTARG" in debug|info|warn|error) LEVEL=$OPTARG ;; *) die "invalid log level: $OPTARG" ;; esac ;;
            :)  usage >&2; die "option -$OPTARG requires an argument" ;;
            \?) usage >&2; die "invalid option -$OPTARG" ;;
        esac
    done
    shift $((OPTIND - 1))

    pkgs=""
    [ -z "$MANIFEST" ] || pkgs=$(read_manifest "$MANIFEST")
    # shellcheck disable=SC2086
    set -- $pkgs "$@"
    [ "$#" -ge 1 ] || die "no packages specified (use -f MANIFEST or name packages)"

    MGR=$(detect_mgr) || die "no supported package manager found"
    log info "package manager: $MGR"

    log info "refreshing package index"
    refresh_index

    todo=""
    for p in "$@"; do
        if is_installed "$p"; then log debug "present: $p"
        else log info "missing: $p"; todo="$todo $p"; fi
    done

    if [ -n "$todo" ]; then
        log info "installing:$todo"
        # shellcheck disable=SC2086
        install_pkgs $todo
        log info "done"
    else
        log info "all packages already present"
    fi
}
main "$@"
