# dotfiles-et-al

Personal dotfiles and unnecesarily complicated bootstrap system.

- **Cross-distro**: One config; many package managers.
- **Declarative**: It _is_ about the destination; NOT the journey
- **Idempotent**: Paranoia is a feature.
- **Previewable**: Regret is cheaper in dry-run mode.
- **Pinned**: Tagged versions stay still.

---

## Quickstart

Fetch `bootstrap.sh` and run it with a profile. Replace `<profile>` with
`minimal`, `server`, `laptop` or `desktop`.

**curl**

```sh
curl -fsSL https://raw.githubusercontent.com/Obbaron/dotfiles-et-al/main/bootstrap.sh -o bootstrap.sh \
  && chmod +x bootstrap.sh \
  && ./bootstrap.sh <profile>
```

**wget**

```sh
wget -qO bootstrap.sh https://raw.githubusercontent.com/Obbaron/dotfiles-et-al/main/bootstrap.sh \
  && chmod +x bootstrap.sh \
  && ./bootstrap.sh <profile>
```

#### Notes
- Profile is positional: `./bootstrap.sh desktop` (not a flag)
- bootstrap.sh is the only file you manually download
- Forking? Override REPO or REPO_URL, cut a release, and tag it **v1.0.0**

---

## Table of contents

- [Requirements](#requirements)
- [Architecture](#architecture)
- [Run lifecycle](#run-lifecycle)
- [Pipeline](#pipeline)
- [`config.toml` reference](#configtoml-reference)
- [Package-name resolution](#package-name-resolution)
- [Usage and recipes](#usage-and-recipes)
- [Idempotency and safety](#idempotency-and-safety)
- [Files](#files)
- [Conventions](#conventions)
- [Cutting a release](#cutting-a-release)
- [Fine print](#known-caveats)

---

## Requirements

The bootstrap script installs the first two for you when it can; the rest are situational.

- **git ≥ 2.25**: required for cone-mode sparse checkout
- **Python ≥ 3.11**: required for the standard-library `tomllib` parser
- **Supported package manager**: `apt-get`, `dnf`/`dnf5`/`yum`, `pacman`, `zypper`, `apk`, `emerge`, `xbps-install`.
- **Network access**: to GitHub (repo + Nerd Fonts) and optionally `repology.org` for cross-distro package name lookups
- **root or `sudo`**: for system-level package installs, system services, and `sudo = true` commands. User-scope work needs neither.
- **systemd**: only for the `services` step. A profile declaring services on a non-systemd host fails fast (see [Fine print](#fine_print)).

---

## Architecture

```
bootstrap.sh ──► configure.py ──► install-pkg.sh
  (shell)          (python)          (shell)
                      ▲
                      │ reads
                 config.toml
```

| Component        | Language   | Responsibility                                                            |
|------------------|------------|---------------------------------------------------------------------------|
| `bootstrap.sh`   | POSIX sh   | Ensure git + Python, obtain the repo at a pinned tag, hand off.           |
| `configure.py`   | Python     | Read config, resolve the profile, apply every step in order.             |
| `install-pkg.sh` | POSIX sh   | Detect the package manager, resolve names, install packages.             |
| `config.toml`    | TOML       | Declarative source of truth: profiles and the modules they compose.      |

- `install-pkg.sh` is fully self-contained and usable on its own.

---

## Run lifecycle

End-to-end when you run `./bootstrap.sh <profile>`.

### `bootstrap.sh`

1. **Ensure dependencies.**
   - Checks `git --version` against the 2.25 minimum and probes for a Python ≥ 3.11 interpreter
   - Installs whatever is missing via the detected package manager (using `sudo` when not root)
   - Checks agains and fails if the versions are still too old
2. **Obtain the repo at `REF`, into `REPO_HOME`.**
   - **First run:** `git clone --branch <REF> --sparse` - a cone-mode sparse checkout of **root files only** (`configure.py`, `config.toml`, `install-pkg.sh`)
   - **Re-run:** `git fetch --tags origin` followed by a non-forced `checkout <REF>`
   - If `REPO_HOME` exists but is not a git repo, refuses rather than overwrite
3. **Hand off.**
   - `exec configure.py <profile>`, passing the arguments straight through to python

**Environment variables**

| Variable    | Default                                              | Purpose                                   |
|-------------|------------------------------------------------------|-------------------------------------------|
| `REF`       | `v1.0.0`                                              | Git tag/ref to clone and check out.       |
| `REPO`      | `Obbaron/dotfiles-et-al`                             | `owner/name` used to build the clone URL. |
| `REPO_URL`  | `https://github.com/$REPO.git`                       | Full clone URL (override for other forges).|
| `REPO_HOME` | `${XDG_DATA_HOME:-$HOME/.local/share}/dotfiles-et-al`| Where the repo lives on disk.             |
| `DRY_RUN`   | *(unset)*                                            | If set, report actions but change nothing.|

### `configure.py`

Invoked as `configure.py <profile> [-n|--dry-run]`. It derives its own repo
location from its path on disk (so `$REPO_HOME` expands correctly in config
values), then:

1. **Ensures its own infra dirs**: `$XDG_CONFIG_HOME/dotfiles-et-al` and `~/.local/bin`.
2. **Seeds the per-machine config**: copies the repo's `config.toml` to `$XDG_CONFIG_HOME/dotfiles-et-al/config.toml` only when there is no usable config there:
   - *missing or empty* → seed it
   - *present and valid* → leave it untouched
   - *present but broken* → refuse (no clobber)
3. **Resolves the profile** to an ordered list of `(step, module)` pairs (see [profile resolution](#profile-resolution))
4. **Applies each step in pipeline order** (see [pipeline](#pipeline))

**Argument / environment summary**

| Input                 | Meaning                                                        |
|-----------------------|----------------------------------------------------------------|
| `profile` (positional)| Profile name defined under `[profiles]`.                       |
| `-n`, `--dry-run`     | Show what each step would do, changing nothing.                |
| `NERD_FONTS_VERSION`  | Nerd Fonts release tag (default `v3.4.0`; use `latest` for the newest). |

### `install-pkg.sh`

`configure.py` writes the profile's canonical package names to a transient
manifest and calls `install-pkg.sh -f <manifest>`. The installer detects the
package manager, resolves each name to a real distro package, and installs the
ones that are missing. It is also a standalone tool (see
[Usage and recipes](#usage-and-recipes)).

---

## Piepline

Steps always run in this fixed order, regardless of how a profile lists them:

```
packages → directories → git → files → fonts → links → services → commands
```

Only the modules your profile resolves to are applied. Every step is a no-op if
the profile pulls in nothing for it.

### 1. `packages`

- **Purpose:** install system packages.
- **How:** `configure.py` collects the **canonical** names (the `name` field, or a bare string), de-duplicates them, and hands them to `install-pkg.sh`.
- **Resolution** to a real distro package name happens inside `install-pkg.sh` (see [Package-name resolution](#package-name-resolution)).

### 2. `directories`

- **Purpose:** create directories, optionally with an explicit mode and/or as a registered XDG user dir.
- **Behavior:** `mkdir -p`; applies `chmod` when a `mode` is given; when a `label` is given, registers the path as an XDG user directory. Prefers the `xdg-user-dirs-update` tool, falling back to upserting `~/.config/user-dirs.dirs` (a re-run replaces the existing line rather than duplicating it).

### 3. `git`

- **Purpose:** clone *other* repositories into place.
- **Behavior:** clones `{ url }` into `{ target }/<repo-name>` when the destination is absent; skips it when present; a clone failure is fatal.
- **NOTE:** this step does **not** manage the dotfiles repo itself. `bootstrap.sh` owns that at `$REPO_HOME`.

**Sparse-checkout widening.** Immediately after the git step, `configure.py`
widens the repo's cone sparse-checkout to include exactly the top-level
directories referenced by the profile's `links` (`src`) and `files` (`source`)
entries. This makes those tool directories available before the `files` and
`links` steps need them, without checking out the entire repo.

### 4. `files`

- **Purpose:** materialize individual files.
- **Three forms:**
  - `{ path, mode }`: ensure the file exists (create empty if absent, never overwriting existing content), then `chmod`.
  - `{ path, mode, content }`: overwrite with the given inline content on every apply.
  - `{ path, mode, source }`: copy from `source` on every apply.
- `content` and `source` are mutually exclusive. Parent directories are not created implicitly; pull in a `directories` module via `requires`.

### 5. `fonts`

- **Purpose:** install Nerd Fonts.
- **Behavior:** downloads each named font's release zip from the Nerd Fonts repo and extracts it into its own subdirectory under `~/.local/share/fonts/`. Skips a font that is already present and non-empty. After any install, reruns `fc-cache -f` (best-effort: warns, not fails).
- **Version** is controlled by `NERD_FONTS_VERSION` (default `v3.4.0`, or `latest`).

### 6. `links`

- **Purpose:** link (or copy) config files from the repo into your home directory.
- **Two forms:**
  - `{ src, dest }`: create a symlink `dest → src`.
  - `{ src, dest, copy = true }`: copy `src` to `dest` instead of linking.
- **Safety:** an existing **symlink with the correct target** is left alone; an existing symlink with the *wrong* target is retargeted; a **real file** at `dest` is moved aside to `dest.bak` before linking (and the run refuses if a `.bak` already exists, rather than lose two versions).
- Paths expand `~` and environment variables: `$REPO_HOME` points at the repo checkout.

### 7. `services`

- **Purpose:** enable/disable and start/stop systemd services.
- **Fields:** `{ name, enabled, started, scope }`.
  - `enabled`: `true` enables, `false` disables, absent leaves it untouched.
  - `started`: `true` starts, `false` stops, absent leaves it untouched.
  - `scope`: `system` (default; escalates via `sudo` when not root) or `user` (`systemctl --user`, never sudo).
- **Requires systemd.** With services declared and no `systemctl` present, a real run fails fast; silently leaving a declared service unmanaged is treated as worse than a hard error.

### 8. `commands`

- **Purpose:** do whatever wasn't important enough to deserve its own first-class abstraction.
- **Fields:** `{ run, desc, cwd, creates, unless, sudo }`.
  - `run`: the command (executed via `sh -c`, so pipes and redirects work).
  - `desc`: a human-readable label for logs.
  - `cwd`: working directory (must exist at run time).
  - `creates`: skip if this path already exists.
  - `unless`: skip if this shell check exits `0`.
  - `sudo`: `true` escalates **both** the command and its `unless` guard (default `false`).
- **Semantics:** an unguarded command always runs. A failing `run` is fatal; a nonzero `unless` is *not* an error.

---

## `config.toml` reference

`config.toml` declares **profiles** and the **modules** they compose. Modules are
grouped by step (`[packages.minimal]`, `[links.bash]`, and so on).

### Profiles

A profile is a list of module references applied to bring a machine to a desired
state. The shipped profiles:

- **`minimal`**: baseline of core CLI packages, base directories, and bash links.
- **`server`**: minimal plus networking/firewall/utility packages, the ufw service, and a default-deny firewall command.
- **`desktop`**: minimal plus terminal and dev tooling, XDG user dirs, project repos, JetBrains Mono, and bash + vim links.

### References and the `*` wildcard

A reference is `step.module`:

- `packages.minimal`: the `minimal` module of the `packages` step.
- `*.minimal`: the `minimal` module under **every** step that defines one (packages, directories, git, files, …). This is how profiles pull a whole "minimal" slice in one line.

### `requires`

Any module may declare `requires = ["step.module", …]` to pull other modules in
transitively. For example, a `links` module requires the `directories` module
that creates its destination's parent, and a `services` module requires the
`packages` module to installs its binary. Resolution follows `requires` to a
fixed point, then emits the full set in pipeline order.

### Item forms by step

| Step          | Bare string means…        | Table form                                                              |
|---------------|---------------------------|-------------------------------------------------------------------------|
| `packages`    | canonical name = command  | `{ name, alias }` when they differ (`alias` is the command; `name` installs). |
| `directories` | path, default mode         | `{ path, mode }` and/or `{ path, label }` (register as an XDG user dir). |
| `git`         | —                          | `{ url, target }` (cloned into `target/<repo-name>` if absent).         |
| `files`       | —                          | `{ path, mode }` / `{ path, mode, content }` / `{ path, mode, source }`.|
| `fonts`       | font name                  | —                                                                       |
| `links`       | —                          | `{ src, dest }` or `{ src, dest, copy = true }`.                        |
| `services`    | —                          | `{ name, enabled, started, scope }`.                                    |
| `commands`    | —                          | `{ run, desc, cwd, creates, unless, sudo }`.                           |

### Path expansion

Values that name paths expand `~` and environment variables. In particular,
`$REPO_HOME` resolves to the repo checkout, so link sources read as
`$REPO_HOME/bash/.bashrc`, independent of where the repo lives.

---

## Package-name resolution

The same tool ships across many distros, but the *package* is often named
differently (`nvim` is `neovim`; Debian splits `p7zip` into `p7zip-full`).
`install-pkg.sh` resolves each canonical name through a short cascade and stops
at the first that the local package manager actually offers:

1. **Built-in table**: a small set of known mappings (e.g. `nvim → neovim`, on apt: `p7zip → p7zip-full`); otherwise the name is passed through unchanged.
2. **Availability probe**: if the candidate is already installed or exists in the configured repos, use it.
3. **[Repology](https://repology.org) lookup**: query the API for the name used by the local distro *family*, preferring the binary package name. Uses `jq` + `curl`/`wget` when available, and falls back to a small Python (`urllib`) implementation.

If nothing resolves, the run stops with a clear error listing the unresolved
names. It never guesses or installs something unexpected.

**Distro family** is detected from the package manager, and for apt/dnf-family
systems refined via `/etc/os-release` (so Ubuntu, Debian, Fedora, RHEL-likes,
and their derivatives map correctly).

---

## Usage and recipes

### Run a profile

```sh
./bootstrap.sh desktop
```

### Dry run

There are **two dry-run layers**, as the bootstrap and orchestrator are
separate programs:

```sh
# Preview the WHOLE run: dependency checks, clone, and the handoff
# bootstrap does not actually invoke configure.py in this mode
DRY_RUN=1 ./bootstrap.sh server

# Clone/update the repo then preview each configure.py step
# (-n is passed through to configure.py.)
./bootstrap.sh server -n
```

- Use `DRY_RUN=1` to see what the bootstrap itself would do.
- Use `-n` to see what the profile's steps would do against an already-obtained repo.

### Test against an unreleased ref

```sh
REF=main ./bootstrap.sh minimal
```

### Use another fork or forge

```sh
REPO=you/your-dotfiles ./bootstrap.sh desktop
# for a non-GitHub URL:
REPO_URL=https://git.example.com/you/dotfiles.git ./bootstrap.sh desktop
```

### Pin or float the Nerd Fonts version

```sh
NERD_FONTS_VERSION=latest ./bootstrap.sh desktop
```

### Run `install-pkg.sh` on its own

```sh
./install-pkg.sh gcc ripgrep            # install named packages
./install-pkg.sh -f manifest.txt        # install from a manifest (one name per line; # = comment)
./install-pkg.sh -n -l debug -f m.txt   # dry run, verbose logging
```

Full option list:

```
Usage: install-pkg.sh [-h] [-n] [-t] [-l LEVEL] [-f MANIFEST] [PACKAGE...]

  -h            show help
  -n            dry run: print commands instead of running them
  -t            prefix log lines with UTC timestamp
  -l LEVEL      log level: debug|info|warn|error (default: info)
  -f MANIFEST   read package names from MANIFEST (one per line; # = comment)
  PACKAGE...    packages to install, in addition to any manifest
```

### Edit your per-machine config

After the first run, your live config is at
`$XDG_CONFIG_HOME/dotfiles-et-al/config.toml` (typically
`~/.config/dotfiles-et-al/config.toml`). Edits there are preserved across
re-runs; the repo copy is only used to seed a machine that has none.

---

## Idempotency and safety

The whole pipeline is designed to be re-run safely:

- **Repo:** re-runs `fetch` + `checkout` rather than re-cloning.
- **Packages:** already-installed packages are skipped.
- **Directories / files:** `mkdir -p` and ensure-exists never destroy content; modes are re-applied.
- **git repos:** existing checkouts are skipped.
- **Fonts:** an already-installed font is skipped; the cache is rebuilt only if something changed.
- **Links:** a correct symlink is left alone; a real file is backed up to `.bak` before being replaced, and the run refuses rather than overwrite an existing `.bak`.
- **Services:** `systemctl` operations are idempotent.
- **Commands:** `creates`/`unless` guards make guarded commands no-ops once satisfied.
- **Config:** a valid per-machine config is never overwritten; a broken one is refused, not clobbered.

The governing principle is simple: **Never silently destroy user data. Never silently ignore failure. If something looks dangerous, stop and complain instead.**

---

## Files

| File             | Role                                                             |
|------------------|------------------------------------------------------------------|
| `bootstrap.sh`   | Entry point; ensures deps, obtains the repo at `REF`, hands off. |
| `configure.py`   | Orchestrator; reads config, resolves the profile, applies steps. |
| `install-pkg.sh` | Package installer (manifest / CLI-driven), with name resolution. |
| `config.toml`    | Declarative config: profiles, packages, dirs, git, files, fonts, links, services, commands. |

---

## Conventions

- **Shell is POSIX `sh`** (`#!/bin/sh`): runs under dash, busybox, and bash (including Alpine). ShellCheck-clean apart from the accepted `local` (SC3043) and the intentional word-split (SC2086) sites.
- **Python** targets 3.11+, is type-hinted, Black-formatted, and Ruff-clean.
- **Logging to stderr, data to stdout;** config/user errors exit with a clear message.
- **Package-manager support:** apt-get, dnf/dnf5/yum, pacman, zypper, apk, emerge, xbps-install. Detection probes `PATH` for the binary, so distro derivatives resolve correctly.

---

## Cutting a release

- `bootstrap.sh` pins `REF` to a release tag so a given tag always resolves the same way.
- When cutting a new tag, **bump `REF` in `bootstrap.sh`** so a fresh bootstrap fetches the matching root files.
- The repo is obtained over **git** (clone/fetch/checkout); there is no raw-file fetching to reconfigure if you move forges. Just set `REPO_URL`.

---

## Fine print

- **systemd only**: if you ask it to manage services on a non-systemd machine, it declines to engage in creative interpretation.
- **Network access**: assumes GitHub and Repology exist; firewall disagreement may render some features theoretical.
- **sudo**: occasionally required. This is less a design choice than an operating-system tradition.

This repository does not attempt to solve the general dotfiles problem. Rather it solves a much narrower problem: recreating _my_ particular environment that may or may not have been a good idea in the first place.
