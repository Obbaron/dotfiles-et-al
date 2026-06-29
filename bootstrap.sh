#!/bin/sh
#
# bootstrap.sh — shell entry point for the pipeline.
#
# Ensures the bootstrap dependencies are present, then hands off to Python:
#   * python >= MIN_PY_MAJOR.MIN_PY_MINOR   (version-checked, not just present)
#   * git, curl                             (presence-checked)
#
# This step must be shell: you can't use Python to install Python. Once Python
# is available it takes over (config parsing, directories, repos) and may call
# setup.sh to install application packages from a generated manifest.
#
# Usage:
#   bootstrap.sh [ARGS...]      ARGS are passed through to the Python entry point.
#
# Env knobs:
#   PYTHON_ENTRY   Python program to exec after bootstrap (default: main.py
#                  beside this script).
#   PKG_DRY_RUN    if set, detect and report but install nothing and don't exec.
#   LOG_LEVEL      debug|info|warn|error (default: info). debug shows "present".

set -eu

# --- locate and load the helper libraries -----------------------------------
# shellcheck disable=SC1007
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=log.sh disable=SC1091
. "$SCRIPT_DIR/log.sh"
# shellcheck source=pkg.sh disable=SC1091
. "$SCRIPT_DIR/pkg.sh"

# --- configuration ----------------------------------------------------------
# shellcheck disable=SC2034
LOG_TAG=bootstrap

# Minimum acceptable Python.
MIN_PY_MAJOR=3
MIN_PY_MINOR=11

# Python program to hand off to once the system is ready.
PYTHON_ENTRY="${PYTHON_ENTRY:-$SCRIPT_DIR/main.py}"

# Pipeline-wide knobs, exported so child stages (incl. setup.sh) inherit them.
PKG_DRY_RUN="${PKG_DRY_RUN:-}"
LOG_LEVEL="${LOG_LEVEL:-}"
LOG_TIMESTAMP="${LOG_TIMESTAMP:-}"
export PKG_DRY_RUN LOG_LEVEL LOG_TIMESTAMP

# --- python detection -------------------------------------------------------
#######################################
# Echo the path of the first Python interpreter on PATH that is at least
# MIN_PY_MAJOR.MIN_PY_MINOR. Asks the interpreter its own version rather than
# parsing --version text. Tries specific minor names before the generic ones.
# Outputs:   interpreter path on stdout (on success).
# Returns:   0 if a suitable interpreter was found, 1 otherwise.
#######################################
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

# --- main -------------------------------------------------------------------
main() {
    local py need pkg

    # git and curl: simple presence checks.
    need=""
    for pkg in git curl; do
        if pkg_is_installed "$pkg"; then
            log_debug "present: $pkg"
        else
            log_info "missing: $pkg"
            need="$need $pkg"
        fi
    done

    # python: a VERSION check, not a presence check. Queue the distro default
    # only if no suitable interpreter already exists.
    if py=$(find_python); then
        log_info "python ok: $py ($("$py" --version 2>&1))"
    else
        log_info "no python >= $MIN_PY_MAJOR.$MIN_PY_MINOR found; will install python3"
        need="$need python3"
    fi

    # Install whatever is missing, once.
    if [ -n "$need" ]; then
        log_info "refreshing package index"
        pkg_update
        log_info "installing:$need"
        # shellcheck disable=SC2086
        pkg_install $need
    fi

    # In dry-run nothing was really installed, so don't verify-or-exec.
    if [ -n "${PKG_DRY_RUN:-}" ]; then
        log_info "dry run: would verify python and exec $PYTHON_ENTRY"
        return 0
    fi

    # Re-verify python after a real install. If the distro's python3 is older
    # than required, stop with guidance instead of conjuring a newer one.
    if [ -z "$py" ]; then
        py=$(find_python) || log_fatal "python >= $MIN_PY_MAJOR.$MIN_PY_MINOR not available after installing python3 — install a newer Python (e.g. a backport or PPA) and re-run"
        log_info "python ok: $py ($("$py" --version 2>&1))"
    fi

    [ -r "$PYTHON_ENTRY" ] || log_fatal "python entry point not found: $PYTHON_ENTRY"
    log_info "handing off to python: $PYTHON_ENTRY"
    exec "$py" "$PYTHON_ENTRY" "$@"
}

main "$@"
