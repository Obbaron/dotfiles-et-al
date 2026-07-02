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
REPO_FAMILY=""
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
resolve_name() {
    local name="$1"
    case "$1" in
        # editors
        nvim) name=neovim ;;

        # archives / compression
        p7zip) case "$MGR" in apt-get) name=p7zip-full ;; esac ;;
        xz)    case "$MGR" in apt-get) name=xz-utils ;; esac ;;

        # file / search tools
        fd|fd-find)
            case "$MGR" in
                apt-get|dnf|dnf5|yum) name=fd-find ;;
                *)                    name=fd ;;
            esac ;;

        # crypto
        gpg|gnupg)
            case "$MGR" in
                dnf|dnf5|yum) name=gnupg2 ;;
                *)            name=gnupg ;;
            esac ;;

        # build toolchain
        g++)
            case "$MGR" in
                dnf|dnf5|yum) name=gcc-c++ ;;
                pacman)       name=gcc ;;
                *)            name=g++ ;;
            esac ;;
        rustc)
            case "$MGR" in
                apt-get) name=rustc ;;
                *)       name=rust ;;
            esac ;;

        # python
        python3) case "$MGR" in pacman) name=python ;; esac ;;
        pip|pip3)
            case "$MGR" in
                pacman) name=python-pip ;;
                apk)    name=py3-pip ;;
                *)      name=python3-pip ;;
            esac ;;

        # javascript
        node) name=nodejs ;;

        # networking
        ssh)
            case "$MGR" in
                pacman)              name=openssh ;;
                dnf|dnf5|yum|zypper) name=openssh-clients ;;
                *)                   name=openssh-client ;;
            esac ;;
        sshd)
            case "$MGR" in
                pacman) name=openssh ;;
                *)      name=openssh-server ;;
            esac ;;
        dig)
            case "$MGR" in
                apt-get)             name=dnsutils ;;
                dnf|dnf5|yum|zypper) name=bind-utils ;;
                apk)                 name=bind-tools ;;
            esac ;;
        ping)
            case "$MGR" in
                apt-get)             name=iputils-ping ;;
                dnf|dnf5|yum|pacman) name=iputils ;;
            esac ;;
        ifconfig|netstat) name=net-tools ;;

        # containers
        docker) case "$MGR" in apt-get) name=docker.io ;; esac ;;
    esac
    printf '%s\n' "$name"
}
pkg_exists() {
    case "$MGR" in
        apt-get)      apt-cache show "$1" >/dev/null 2>&1 ;;
        dnf|dnf5|yum) "$MGR" -q info "$1" >/dev/null 2>&1 ;;
        zypper)       zypper --non-interactive -q se -x "$1" >/dev/null 2>&1 ;;
        pacman)       pacman -Si "$1" >/dev/null 2>&1 ;;
        apk)          [ -n "$(apk search -e "$1" 2>/dev/null)" ] ;;
        emerge)       emerge -pq "$1" >/dev/null 2>&1 ;;
        xbps-install) xbps-query -R "$1" >/dev/null 2>&1 ;;
        *)            return 0 ;;   # unknown manager
    esac
}
detect_family() {
    case "$MGR" in
        pacman)       printf 'arch\n' ;;
        apk)          printf 'alpine\n' ;;
        xbps-install) printf 'void\n' ;;
        emerge)       printf 'gentoo\n' ;;
        zypper)       printf 'opensuse\n' ;;
        apt-get|dnf|dnf5|yum) _family_from_os_release ;;
        *)            printf '\n' ;;
    esac
}
_family_from_os_release() {
    local id=""
    [ -r /etc/os-release ] && id=$(sed -n 's/^ID=//p' /etc/os-release | tr -d '"' | head -n1)
    case "$id" in
        ubuntu|linuxmint|pop|elementary|neon|zorin) printf 'ubuntu\n' ;;
        debian|raspbian|devuan|kali|mx)             printf 'debian\n' ;;
        fedora)                                      printf 'fedora\n' ;;
        rhel|centos|rocky|almalinux|ol|amzn)         printf 'centos\n' ;;
        *)                                           printf '%s\n' "$id" ;;
    esac
}
_http_get() {
    local ua
    ua="dotfiles-et-al installer (+https://github.com/Obbaron)"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --max-time 10 -A "$ua" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- --timeout=10 -U "$ua" "$1"
    else
        return 1
    fi
}
_repology_jq() {
    local body
    body=$(_http_get "https://repology.org/api/v1/project/$1") || return 1
    [ -n "$body" ] || return 1
    printf '%s' "$body" | jq -r --arg fam "$REPO_FAMILY" '
        [ .[]
          | select(.repo | startswith($fam))
          | (.binname // .srcname)
          | select(. != null)
        ][0] // empty
    ' 2>/dev/null
}
_repology_python() {
    python3 - "$1" "$REPO_FAMILY" <<'PY' 2>/dev/null
import json, sys, urllib.parse, urllib.request

name, family = sys.argv[1], sys.argv[2]
url = "https://repology.org/api/v1/project/" + urllib.parse.quote(name)
try:
    req = urllib.request.Request(
        url, headers={"User-Agent": "dotfiles-et-al installer (+https://github.com/Obbaron)"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
except Exception:
    sys.exit(2)
# first entry whose repo matches our family; prefer the binary name
for entry in data:
    if entry.get("repo", "").startswith(family):
        resolved = entry.get("binname") or entry.get("srcname")
        if resolved:
            print(resolved)
            sys.exit(0)
sys.exit(1)
PY
}
repology_name() {
    [ -n "$REPO_FAMILY" ] || return 1
    if command -v jq >/dev/null 2>&1 \
        && { command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1; }; then
        _repology_jq "$1"
    elif command -v python3 >/dev/null 2>&1; then
        _repology_python "$1"
    else
        return 1
    fi
}
resolve_pkg() {
    local cand rep
    cand=$(resolve_name "$1")
    if is_installed "$cand" || pkg_exists "$cand"; then
        printf '%s\n' "$cand"; return 0
    fi
    rep=$(repology_name "$cand") || rep=""
    if [ -n "$rep" ] && pkg_exists "$rep"; then
        log info "repology: $cand -> $rep"
        printf '%s\n' "$rep"; return 0
    fi
    return 1
}

# Manifest
read_manifest() {
    [ -r "$1" ] || die "cannot read manifest: $1"
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line#"${line%%[![:space:]]*}"}   # trim leading whitespace
        line=${line%"${line##*[![:space:]]}"}   # trim trailing whitespace
        case "$line" in ''|\#*) continue ;; esac
        printf '%s\n' "$line"
    done < "$1"
    return 0
}


main() {
    local opt pkgs todo p r unresolved
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
    REPO_FAMILY=$(detect_family)

    log info "refreshing package index"
    refresh_index

    todo=""
    unresolved=""
    for p in "$@"; do
        if r=$(resolve_pkg "$p"); then
            [ "$r" = "$p" ] || log debug "resolved: $p -> $r"
            if is_installed "$r"; then log debug "present: $r"
            else log info "missing: $r"; todo="$todo $r"; fi
        else
            log warn "unresolved: $p"; unresolved="$unresolved $p"
        fi
    done
    [ -z "$unresolved" ] || die "could not resolve package(s):$unresolved (not in table, not in repos, no Repology match)"

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
