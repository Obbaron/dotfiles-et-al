# .dotfiles-et-al

Personal dotfiles repo and bootstrap script.

## Quickstart

Curl bootstrap script; replace `<profile>` with desired profile:

```sh
curl -fsSL https://raw.githubusercontent.com/Obbaron/.dotfiles-et-al/main/bootstrap.sh -o bootstrap.sh \
  && chmod +x bootstrap.sh \
  && ./bootstrap.sh <profile>
```
Or, with wget:

```sh
wget -qo- https://raw.githubusercontent.com/Obbaron/.dotfiles-et-al/main/bootstrap.sh -o bootstrap.sh \
  && chmod +x bootstrap.sh \
  && ./bootstrap.sh <profile>
```

## Flow

```
bootstrap.sh ──► configure.py ──► install-pkg.sh
  (shell)          (python)          (shell)
```

1. **bootstrap.sh** — the only thing fetched on its own (curl/wget). It:
   - ensures the dependencies **python ≥ 3.11** and **git**;
   - fetches the root files (`configure.py`, `config.toml`, `install-pkg.sh`),
     pinned to a tag, into a temp dir;
   - hands off to `configure.py` and steps out of the way.
2. **configure.py** — the orchestrator. Reads `config.toml`, resolves the
   selected profile, generates a package manifest, calls `install-pkg.sh`,
   sparse-clones the repo at the same tag, then applies directories, files,
   links, services, and commands. Owns and removes the temp dir.
3. **install-pkg.sh** — self-contained package installer. Detects the system
   package manager and installs from a manifest and/or named packages.

## Usage

```sh
# typical: fetch bootstrap.sh, then run it with a profile
./bootstrap.sh --profile desktop

# preview without changing anything
DRY_RUN=1 ./bootstrap.sh --profile server

# test against an unreleased ref
REF=main ./bootstrap.sh --profile minimal
```

`install-pkg.sh` is also usable on its own:

```sh
./install-pkg.sh gcc ripgrep            # install named packages
./install-pkg.sh -f manifest.txt        # install from a manifest
./install-pkg.sh -n -l debug -f m.txt   # dry run, verbose
```

## Files

| file             | role                                                       |
|------------------|------------------------------------------------------------|
| `bootstrap.sh`   | entry point; ensures deps, fetches root files, hands off   |
| `configure.py`   | orchestrator; reads config, applies the profile            |
| `install-pkg.sh` | package installer (manifest- and CLI-driven)               |
| `config.toml`    | declarative config: profiles, packages, dirs, links, …     |

## Conventions

- Shell is **POSIX `sh`** (`#!/bin/sh`): runs under dash/busybox/bash, Alpine
  included. ShellCheck-clean apart from the accepted `local` (SC3043) and the
  intentional word-split (SC2086) sites.
- Package-manager support: apt-get, dnf/dnf5/yum, pacman, zypper, apk, emerge,
  xbps-install. Detection probes PATH for the binary, so distro derivatives
  resolve correctly.

## Release note

`bootstrap.sh` pins `REF` to a release tag. When cutting a new tag, **bump
`REF` in `bootstrap.sh`** so it fetches the matching root files. `RAW_BASE`
hardcodes GitHub's raw-URL scheme — change it if the repo moves forges.
