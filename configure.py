#!/usr/bin/env python3
"""configure.py - invoked by bootstrap.sh

  1. derive its own home (REPO_HOME) from its location on disk
  2. ensure the infra dirs it needs before it can read config
  3. seed the per-machine config if absent
  4. resolve the chosen profile to an ordered list of modules
  5. apply them
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path


STEP_ORDER = (
    "packages", "directories", "git", "files",
    "fonts", "links", "services", "commands",
)

def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))

CONFIG_DIR = xdg_config_home() / "dotfiles-et-al"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LOCAL_BIN = Path.home() / ".local" / "bin"

NERD_FONTS_REPO = "https://github.com/ryanoasis/nerd-fonts"
NERD_FONTS_VERSION = os.environ.get("NERD_FONTS_VERSION", "v3.4.0")
FONTS_DIR = "~/.local/share/fonts"


def repo_home() -> Path:
    return Path(__file__).resolve().parent


def expand_path(raw: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(raw)))


def ensure_infra_dirs() -> None:
    for d in (CONFIG_DIR, LOCAL_BIN):
        d.mkdir(parents=True, exist_ok=True)


def seed_config(template: Path) -> None:
    """Copy the repo template to CONFIG_PATH only when no usable config exists.
      - missing or empty   -> seed 
      - present & valid    -> leave it untouched
      - present but broken -> refuse, rather than clobber what may be a user edit
    """
    if CONFIG_PATH.exists() and CONFIG_PATH.stat().st_size > 0:
        try:
            with CONFIG_PATH.open("rb") as fh:
                tomllib.load(fh)
        
        except tomllib.TOMLDecodeError as exc:
            sys.exit(
                f"existing config is not valid TOML: {CONFIG_PATH}\n  {exc}\n"
                "fix or remove it, then re-run"
            )
        return
    
    if not template.is_file():
        sys.exit(f"config template missing from repo: {template}")
    
    shutil.copyfile(template, CONFIG_PATH)
    
    print(f"[configure] seeded config -> {CONFIG_PATH}")


def load_config(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    
    except (OSError, tomllib.TOMLDecodeError) as exc:
        sys.exit(f"cannot read config {path}: {exc}")


def modules_in_step(config: dict, step: str) -> list[str]:
    section = config.get(step)
    return list(section.keys()) if isinstance(section, dict) else []


def expand_ref(config: dict, ref: str) -> list[tuple[str, str]]:
    """Expand one profile/requires ref ("step.module") to concrete (step, module)
    pairs. The step may be "*", meaning that module under every step defining it
    E.G. `*.minimal`."""
    if "." not in ref:
        sys.exit(f"invalid ref (want `step.module`): {ref!r}")

    step, module = ref.split(".", 1)
    
    if step == "*":
        pairs = [(s, module) for s in STEP_ORDER if module in modules_in_step(config, s)]
        if not pairs:
            sys.exit(f"ref {ref!r} matched no modules")
        return pairs

    if step not in STEP_ORDER:
        sys.exit(f"unknown step in ref {ref!r}: {step!r}")
    
    if module not in modules_in_step(config, step):
        sys.exit(f"unknown module in ref {ref!r}: {step}.{module}")

    return [(step, module)]


def resolve_profile(config: dict, profile: str) -> list[tuple[str, str]]:
    """Resolve a profile to its (step, module) pairs in pipeline order, pulling
    `requires` in transitively."""
    profiles = config.get("profiles")
    
    if not isinstance(profiles, dict) or profile not in profiles:
        available = ", ".join(sorted((profiles or {}).keys())) or "(none)"
        sys.exit(f"unknown profile: {profile!r} (available: {available})")

    seen: set[tuple[str, str]] = set()
    stack: list[tuple[str, str]] = []
    
    for ref in profiles[profile]:
        stack.extend(expand_ref(config, ref))
    
    while stack:
        node = stack.pop()
        
        if node in seen:
            continue
        
        seen.add(node)
        step, module = node
        section = config.get(step, {}).get(module, {})
        
        for req in section.get("requires", []):
            stack.extend(expand_ref(config, req))

    ordered: list[tuple[str, str]] = []
    
    for step in STEP_ORDER:
        for module in modules_in_step(config, step):
            if (step, module) in seen:
                ordered.append((step, module))
    
    return ordered


def collect_packages(config: dict, modules: list[tuple[str, str]]) -> list[str]:
    """Canonical package names from the resolved packages..

    A bare-string item is its own name; a table item's name is `name` (its
    `alias`, the command, is not what gets installed; install-pkg.sh checks
    presence by package name).
    """
    names: list[str] = []
    seen: set[str] = set()
    
    for step, module in modules:
        if step != "packages":
            continue
        
        for item in config[step][module].get("items", []):
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict) and item.get("name"):
                name = item["name"]
            else:
                sys.exit(f"packages.{module}: item missing a usable name: {item!r}")
            if name not in seen:
                seen.add(name)
                names.append(name)
    
    return names


def _validate_installer(installer: Path) -> None:
    """Statically verify the file is really install-pkg.sh before executing it."""
    try:
        text = installer.read_text(errors="replace")
    
    except OSError as exc:
        sys.exit(f"cannot read {installer}: {exc}")
    
    if "Usage: install-pkg.sh" in text:
        return
    
    header = ""
    
    for line in text.splitlines():
        if line.strip() and not line.startswith("#!"):
            header = line.strip()
            break
    
    sys.exit(
        f"{installer} invalid install-pkg.sh "
        f"(first non-shebang line: {header!r})"
    )


def install_packages(repo_home: Path, names: list[str], dry_run: bool) -> None:
    """Write the names to a transient manifest and hand it to install-pkg.sh -f.
    The manifest is the dumb flat .txt files of package names."""
    if not names:
        print("[configure] packages: none to install")
        return
    
    installer = repo_home / "install-pkg.sh"
    
    if not installer.is_file():
        sys.exit(f"install-pkg.sh not found in repo: {installer}")
    
    _validate_installer(installer)

    if dry_run:
        print(f"[configure] packages: would install {len(names)} via install-pkg.sh -f:")
        for name in names:
            print(f"    {name}")
        
        return

    fd, manifest = tempfile.mkstemp(prefix="dotfiles-manifest-", suffix=".txt")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(names) + "\n")
        
        print(f"[configure] packages: installing {len(names)} via {installer.name}")
        
        try:
            subprocess.run(["sh", str(installer), "-f", manifest], check=True)
        
        except subprocess.CalledProcessError as exc:
            sys.exit(f"package install failed (install-pkg.sh exited {exc.returncode})")
    
    finally:
        os.unlink(manifest)


def _parse_dir_item(module: str, item: object) -> tuple[str, str | None, str | None]:
    """Return (path, mode, label) for a directories item. Bare string -> path
    only; table -> path plus optional mode and/or label."""
    if isinstance(item, str):
        return item, None, None
    if isinstance(item, dict) and item.get("path"):
        return item["path"], item.get("mode"), item.get("label")
    sys.exit(f"directories.{module}: item missing a usable path: {item!r}")


def _parse_mode(context: str, mode: str) -> int:
    try:
        return int(str(mode), 8)
    except ValueError:
        sys.exit(f"{context}: invalid octal mode: {mode!r}")


def _xdg_value(path: Path) -> str:
    """Format a path for user-dirs.dirs: "$HOME/rest" under home (matching
    xdg-user-dirs), else absolute path."""
    try:
        rel = path.relative_to(Path.home())
    except ValueError:
        return f'"{path}"'
    return '"$HOME"' if str(rel) == "." else f'"$HOME/{rel}"'


def register_xdg_user_dir(label: str, path: Path, dry_run: bool) -> None:
    """Register path as the XDG user dir named by label. Prefer the official
    xdg-user-dirs-update tool when present."""
    if shutil.which("xdg-user-dirs-update") and _register_xdg_via_tool(label, path, dry_run):
        return
    _register_xdg_via_file(label, path, dry_run)


def _register_xdg_via_tool(label: str, path: Path, dry_run: bool) -> bool:
    """Use `xdg-user-dirs-update --set TYPE PATH`. Returns True on success,
    False if the tool rejected the request so the caller can fall back E.G.
    a non-standard label the tool does not recognize."""
    xtype = label.upper()
    cmd = ["xdg-user-dirs-update", "--set", xtype, str(path)]
    
    if dry_run:
        print(f"[configure] xdg: would run {' '.join(cmd)}")
        return True
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"[configure] xdg: xdg-user-dirs-update failed for {xtype} "
              f"(exit {exc.returncode}); falling back to user-dirs.dirs")
        return False
    
    print(f"[configure] xdg: {xtype} -> {path} (via xdg-user-dirs-update)")
    
    return True


def _register_xdg_via_file(label: str, path: Path, dry_run: bool) -> None:
    """Upsert XDG_<LABEL>_DIR in ~/.config/user-dirs.dirs, replacing any existing
    line for that key so re-runs don't duplicate entries."""
    key = f"XDG_{label.upper()}_DIR"
    entry = f"{key}={_xdg_value(path)}"
    dirs_file = xdg_config_home() / "user-dirs.dirs"

    if dry_run:
        print(f"[configure] xdg: would set {entry} in {dirs_file}")
        return

    lines = dirs_file.read_text().splitlines() if dirs_file.exists() else []
    
    for i, line in enumerate(lines):
        if line.lstrip().startswith(f"{key}="):
            lines[i] = entry
            break
    else:
        lines.append(entry)

    dirs_file.parent.mkdir(parents=True, exist_ok=True)
    dirs_file.write_text("\n".join(lines) + "\n")
    
    print(f"[configure] xdg: {key} -> {_xdg_value(path)} (via user-dirs.dirs)")


def _apply_one_directory(module: str, item: object, dry_run: bool) -> None:
    raw, mode, label = _parse_dir_item(module, item)
    path = expand_path(raw)

    if mode is not None:
        bits = _parse_mode(f"directories.{module}", mode)

    if dry_run:
        print(f"[configure] mkdir -p {path}" + (f" (mode {mode})" if mode else ""))
    else:
        path.mkdir(parents=True, exist_ok=True)
        if mode is not None:
            path.chmod(bits)
        print(f"[configure] dir {path}" + (f" (mode {mode})" if mode else ""))

    if label:
        register_xdg_user_dir(label, path, dry_run)


def apply_directories(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Create every directory declared by the resolved directories modules, in
    pipeline order, applying explicit modes and XDG registrations."""
    dir_modules = [(step, module) for step, module in modules if step == "directories"]
    if not dir_modules:
        return
    
    total = sum(len(config[s][m].get("items", [])) for s, m in dir_modules)
    
    print(f"[configure] directories: {total} item(s) across {len(dir_modules)} module(s)")
    
    for step, module in dir_modules:
        for item in config[step][module].get("items", []):
            _apply_one_directory(module, item, dry_run)


def _parse_git_item(module: str, item: object) -> tuple[str, str]:
    """Return (url, target) for a git item. target is the parent directory the
    repo is cloned into."""
    if isinstance(item, dict) and item.get("url") and item.get("target"):
        return item["url"], item["target"]
    
    sys.exit(f"git.{module}: item needs both url and target: {item!r}")


def _repo_dir_name(url: str) -> str:
    """Directory name a clone of url lands in: the last path segment minus a
    trailing .git (handles scp-style git@host:owner/repo.git too)."""
    tail = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    
    return tail[:-4] if tail.endswith(".git") else tail


def _clone_one(module: str, item: object, dry_run: bool) -> None:
    url, target = _parse_git_item(module, item)
    dest = expand_path(target) / _repo_dir_name(url)

    if dest.exists():
        print(f"[configure] present: {dest} (skip)")
        return
    if dry_run:
        print(f"[configure] git clone {url} -> {dest}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"[configure] cloning {url} -> {dest}")
    
    try:
        subprocess.run(["git", "clone", url, str(dest)], check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"git.{module}: clone failed for {url} (git exited {exc.returncode})")


def apply_git(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Clone every repo declared by the resolved git modules, in pipeline order,
    skipping any whose destination already exists."""
    git_modules = [(step, module) for step, module in modules if step == "git"]
    
    if not git_modules:
        return
    
    total = sum(len(config[s][m].get("items", [])) for s, m in git_modules)
    print(f"[configure] git: {total} repo(s) across {len(git_modules)} module(s)")
    
    for step, module in git_modules:
        for item in config[step][module].get("items", []):
            _clone_one(module, item, dry_run)


def _parse_file_item(module: str, item: object) -> tuple[str, str | None, str | None, str | None]:
    """Return (path, mode, content, source) for a files item. path is required;
    mode is optional; content and source are optional and mutually exclusive."""
    if not (isinstance(item, dict) and item.get("path")):
        sys.exit(f"files.{module}: item needs at least a path: {item!r}")
    
    content = item.get("content")
    source = item.get("source")
    
    if content is not None and source is not None:
        sys.exit(f"files.{module}: item has both content and source (choose one): {item!r}")
    
    return item["path"], item.get("mode"), content, source


def _ensure_file(module: str, path: Path) -> None:
    """Create an empty file if absent; leave an existing file's content intact."""
    if path.exists():
        return
    try:
        path.touch()
    except OSError as exc:
        sys.exit(f"files.{module}: cannot create {path}: {exc} "
                 "(does its parent dir exist? add a directories module to requires)")


def _write_file(module: str, path: Path, content: str) -> None:
    try:
        path.write_text(content)
    except OSError as exc:
        sys.exit(f"files.{module}: cannot write {path}: {exc} "
                 "(does its parent dir exist? add a directories module to requires)")


def _copy_file(module: str, src: Path, path: Path) -> None:
    if not src.exists():
        sys.exit(f"files.{module}: source not found: {src} "
                 "(from a cloned repo? add that git module to requires)")
    try:
        shutil.copyfile(src, path)
    except OSError as exc:
        sys.exit(f"files.{module}: cannot copy {src} -> {path}: {exc}")


def _apply_one_file(module: str, item: object, dry_run: bool) -> None:
    raw, mode, content, source = _parse_file_item(module, item)
    path = expand_path(raw)
    bits = _parse_mode(f"files.{module}", mode) if mode is not None else None

    if content is not None:
        action = f"write {path} ({len(content)} char(s))"
    elif source is not None:
        src = expand_path(source)
        action = f"copy {src} -> {path}"
    else:
        action = f"ensure {path}"
    suffix = f" (mode {mode})" if mode else ""

    if dry_run:
        print(f"[configure] {action}{suffix}")
        return

    if content is not None:
        _write_file(module, path, content)
    elif source is not None:
        _copy_file(module, src, path)
    else:
        _ensure_file(module, path)
    
    if bits is not None:
        path.chmod(bits)
    
    print(f"[configure] {action}{suffix}")


def apply_files(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Materialize every file declared by the resolved files modules, in pipeline
    order: ensure-exists, inline content, or copy-from-source, each then chmod'd."""
    file_modules = [(step, module) for step, module in modules if step == "files"]
    
    if not file_modules:
        return
    
    total = sum(len(config[s][m].get("items", [])) for s, m in file_modules)
    print(f"[configure] files: {total} item(s) across {len(file_modules)} module(s)")
    
    for step, module in file_modules:
        for item in config[step][module].get("items", []):
            _apply_one_file(module, item, dry_run)


def _nerd_font_url(name: str) -> str:
    if NERD_FONTS_VERSION == "latest":
        return f"{NERD_FONTS_REPO}/releases/latest/download/{name}.zip"
    
    return f"{NERD_FONTS_REPO}/releases/download/{NERD_FONTS_VERSION}/{name}.zip"


def _install_font(module: str, name: str, dry_run: bool) -> bool:
    """Download the named Nerd Font's release zip and extract it into its
    own subdir under ~/.local/share/fonts."""
    dest = expand_path(FONTS_DIR) / name
    url = _nerd_font_url(name)

    if dest.is_dir() and any(dest.iterdir()):
        print(f"[configure] present: {dest} (skip)")
        return False
    if dry_run:
        print(f"[configure] fetch {url} -> {dest}/")
        return True

    print(f"[configure] fetching {name} ({NERD_FONTS_VERSION})")
    
    fd, tmpzip = tempfile.mkstemp(prefix=f"nf-{name}-", suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (fixed https host)
                    shutil.copyfileobj(resp, out)
            
            except OSError as exc:
                sys.exit(f"fonts.{module}: download failed for {url}: {exc}")
        
        dest.mkdir(parents=True, exist_ok=True)
        
        try:
            with zipfile.ZipFile(tmpzip) as zf:
                zf.extractall(dest)
        except zipfile.BadZipFile as exc:
            sys.exit(f"fonts.{module}: not a valid zip for {name}: {exc}")
    
    finally:
        os.unlink(tmpzip)
    
    print(f"[configure] installed {name} -> {dest}")
    
    return True


def _rebuild_font_cache(dry_run: bool) -> None:
    """Refresh the fontconfig cache so newly installed fonts are visible.
    Best-effort: missing / failing fc-cache is a warning, not fatal."""
    if dry_run:
        print("[configure] would run fc-cache -f")
        return
    
    if not shutil.which("fc-cache"):
        print("[configure] fc-cache not found; skipping cache rebuild "
              "(fonts will be picked up on the next fontconfig refresh)")
        return
    
    try:
        subprocess.run(["fc-cache", "-f"], check=True)
        print("[configure] font cache rebuilt (fc-cache -f)")
    except subprocess.CalledProcessError as exc:
        print(f"[configure] fc-cache failed (exit {exc.returncode}); "
              "fonts installed but cache not rebuilt")


def apply_fonts(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Install every Nerd Font declared by the resolved fonts modules, then
    rebuild the fontconfig cache once if anything was installed."""
    font_modules = [(step, module) for step, module in modules if step == "fonts"]
    
    if not font_modules:
        return
    
    total = sum(len(config[s][m].get("items", [])) for s, m in font_modules)
    print(f"[configure] fonts: {total} font(s) across {len(font_modules)} module(s)")
    
    installed_any = False
    for step, module in font_modules:
        for item in config[step][module].get("items", []):
            if not isinstance(item, str):
                sys.exit(f"fonts.{module}: item must be a font name string: {item!r}")
            if _install_font(module, item, dry_run):
                installed_any = True
    
    if installed_any:
        _rebuild_font_cache(dry_run)


def _repo_tool_dirs(config: dict, modules: list[tuple[str, str]], repo_home: Path) -> list[str]:
    """Top-level directories under REPO_HOME referenced by the resolved links
    (src) and files (source) — the tool dirs that must be checked out."""
    home = repo_home.resolve()
    dirs: set[str] = set()

    def consider(raw: str | None) -> None:
        if not raw:
            return
        try:
            rel = expand_path(raw).resolve().relative_to(home)
        except ValueError:
            return  # not under the repo
        if rel.parts:
            dirs.add(rel.parts[0])

    for step, module in modules:
        items = config[step][module].get("items", [])
        
        if step == "links":
            for item in items:
                if isinstance(item, dict):
                    consider(item.get("src"))
        
        elif step == "files":
            for item in items:
                if isinstance(item, dict):
                    consider(item.get("source"))
    
    return sorted(dirs)


def widen_sparse_checkout(config: dict, modules: list[tuple[str, str]],
                          repo_home: Path, dry_run: bool) -> None:
    """Widen the repo's cone sparse-checkout to include the tool dirs referenced
    by the profile's links/files."""
    dirs = _repo_tool_dirs(config, modules, repo_home)
    if not dirs:
        return
    
    print(f"[configure] sparse-checkout: widen for {', '.join(dirs)}")
    cmd = ["git", "-C", str(repo_home), "sparse-checkout", "set", *dirs]
    
    if dry_run:
        print(f"[configure] would run: {' '.join(cmd)}")
        return
   
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"sparse-checkout widen failed (git exited {exc.returncode})")


def _parse_link_item(module: str, item: object) -> tuple[str, str, bool]:
    """Return (src, dest, copy) for a links item. src and dest required; copy
    defaults to False (symlink)."""
    if isinstance(item, dict) and item.get("src") and item.get("dest"):
        return item["src"], item["dest"], bool(item.get("copy", False))
    sys.exit(f"links.{module}: item needs both src and dest: {item!r}")


def _backup_real(module: str, dest: Path) -> None:
    """Move a pre-existing file/dir at dest aside to dest.bak before a symlink
    replaces it (refuse if a .bak already exists)."""
    backup = dest.with_name(dest.name + ".bak")
    if backup.exists():
        sys.exit(f"links.{module}: {dest} is a real file and {backup} already exists; "
                 "resolve manually")
    dest.rename(backup)
    print(f"[configure] backup {dest} -> {backup}")


def _apply_one_link(module: str, item: object, dry_run: bool) -> None:
    raw_src, raw_dest, copy = _parse_link_item(module, item)
    src = expand_path(raw_src)
    dest = expand_path(raw_dest)

    if copy:
        if dry_run:
            print(f"[configure] copy {src} -> {dest}")
            return
        if not src.exists():
            sys.exit(f"links.{module}: source not found: {src} "
                     "(repo dir not checked out? it should be via sparse-checkout)")
        try:
            shutil.copyfile(src, dest)
        except OSError as exc:
            sys.exit(f"links.{module}: cannot copy {src} -> {dest}: {exc} "
                     "(parent dir missing? add a directories module to requires)")
        
        print(f"[configure] copy {src} -> {dest}")
        return

    if dest.is_symlink() and dest.readlink() == src:
        print(f"[configure] present: {dest} -> {src} (skip)")
        return

    needs_backup = dest.exists() and not dest.is_symlink()
    if dry_run:
        if needs_backup:
            print(f"[configure] backup {dest} -> {dest.name}.bak")
        print(f"[configure] link {dest} -> {src}")
        return

    if needs_backup:
        _backup_real(module, dest)
    elif dest.is_symlink():
        dest.unlink()  # existing symlink with the wrong target
    
    try:
        dest.symlink_to(src)
    except OSError as exc:
        sys.exit(f"links.{module}: cannot link {dest} -> {src}: {exc} "
                 "(parent dir missing? add a directories module to requires)")
    
    print(f"[configure] link {dest} -> {src}")


def apply_links(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Create/refresh every link declared by the resolved links modules: a
    symlink dest -> src (default), or a copy of src to dest (copy=true)."""
    link_modules = [(step, module) for step, module in modules if step == "links"]
    if not link_modules:
        return
    
    total = sum(len(config[s][m].get("items", [])) for s, m in link_modules)
    print(f"[configure] links: {total} item(s) across {len(link_modules)} module(s)")
    
    for step, module in link_modules:
        for item in config[step][module].get("items", []):
            _apply_one_link(module, item, dry_run)


def _parse_service_item(module: str, item: object) -> tuple[str, bool | None, bool | None, str]:
    """Return (name, enabled, started, scope) for a services item. name is
    required; enabled/started are optional booleans (None = leave that aspect
    untouched); scope is "system" (default) or "user"."""
    if not (isinstance(item, dict) and item.get("name")):
        sys.exit(f"services.{module}: item needs a name: {item!r}")
    
    scope = item.get("scope", "system")
    if scope not in ("system", "user"):
        sys.exit(f"services.{module}: invalid scope {scope!r} (want system|user): {item!r}")
    
    for field in ("enabled", "started"):
        if field in item and not isinstance(item[field], bool):
            sys.exit(f"services.{module}: {field} must be true or false: {item!r}")
    
    return item["name"], item.get("enabled"), item.get("started"), scope


def _run_service_action(module: str, name: str, action: str, scope: str, dry_run: bool) -> None:
    """Run one systemctl action (enable/disable/start/stop) for a service.
    system scope escalates to sudo when we are not root; user scope never does."""
    cmd = ["systemctl", "--user", action, name] if scope == "user" \
        else ["systemctl", action, name]
    
    if scope == "system" and os.geteuid() != 0:
        if not dry_run and not shutil.which("sudo"):
            sys.exit(f"services.{module}: need root or sudo for system service "
                     f"'{name}' (action {action}); re-run as root or install sudo")
        cmd = ["sudo", *cmd]

    if dry_run:
        print(f"[configure] would run: {' '.join(cmd)}")
        return
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"services.{module}: '{action} {name}' failed "
                 f"(systemctl exited {exc.returncode})")
    
    print(f"[configure] {action} {name} ({scope})")


def _apply_one_service(module: str, item: object, dry_run: bool) -> None:
    name, enabled, started, scope = _parse_service_item(module, item)
    if enabled is None and started is None:
        print(f"[configure] service {name}: nothing to do (no enabled/started)")
        return
    if enabled is not None:
        _run_service_action(module, name, "enable" if enabled else "disable", scope, dry_run)
    if started is not None:
        _run_service_action(module, name, "start" if started else "stop", scope, dry_run)


def apply_services(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Enable/disable and start/stop every service declared by the resolved
    services modules, via systemctl. Requires systemd: a missing systemctl is
    fatal when services are declared, since leaving a declared service (e.g. a
    firewall) unmanaged is worse than a hard failure."""
    svc_modules = [(step, module) for step, module in modules if step == "services"]
    if not svc_modules:
        return
    
    total = sum(len(config[s][m].get("items", [])) for s, m in svc_modules)
    print(f"[configure] services: {total} item(s) across {len(svc_modules)} module(s)")
    
    if not shutil.which("systemctl"):
        if not dry_run:
            sys.exit("services: systemctl not found (this step requires systemd); "
                     "run on a systemd host or drop the services module(s) from the profile")
        print("[configure] note: systemctl not found; a real run would fail here")
    
    for step, module in svc_modules:
        for item in config[step][module].get("items", []):
            _apply_one_service(module, item, dry_run)


def _parse_command_item(
    module: str, item: object
) -> tuple[str, str | None, str | None, str | None, str | None, bool]:
    """Return (run, desc, cwd, creates, unless, sudo) for a commands item. run is
    required; the rest are optional (sudo defaults to False)."""
    if not (isinstance(item, dict) and item.get("run")):
        sys.exit(f"commands.{module}: item needs a run field: {item!r}")
    if "sudo" in item and not isinstance(item["sudo"], bool):
        sys.exit(f"commands.{module}: sudo must be true or false: {item!r}")
    return (
        item["run"], item.get("desc"), item.get("cwd"),
        item.get("creates"), item.get("unless"), bool(item.get("sudo", False)),
    )


def _shell_argv(module: str, command: str, sudo: bool, dry_run: bool) -> list[str]:
    """Wrap a command string for `sh -c`, escalating to sudo when sudo=true and
    we are not already root."""
    argv = ["sh", "-c", command]
    
    if sudo and os.geteuid() != 0:
        if not dry_run and not shutil.which("sudo"):
            sys.exit(f"commands.{module}: 'sudo = true' but not root and no sudo "
                     "found; re-run as root or install sudo")
        argv = ["sudo", *argv]
    
    return argv


def _apply_one_command(module: str, item: object, dry_run: bool) -> None:
    run, desc, cwd, creates, unless, sudo = _parse_command_item(module, item)
    label = desc or run
    workdir = expand_path(cwd) if cwd else None

    if dry_run:
        if creates is not None and expand_path(creates).exists():
            print(f"[configure] would skip: {label} (creates exists)")
            return
        
        argv = _shell_argv(module, run, sudo, dry_run=True)
        extra = []
        
        if workdir is not None:
            extra.append(f"cwd={workdir}")
        if unless is not None:
            extra.append(f"unless={unless!r}")
        
        suffix = f" [{', '.join(extra)}]" if extra else ""
        print(f"[configure] would run: {' '.join(argv)}{suffix}")
        
        return

    if workdir is not None and not workdir.is_dir():
        sys.exit(f"commands.{module}: cwd does not exist: {workdir}")
    
    if creates is not None and expand_path(creates).exists():
        print(f"[configure] skip: {label} (creates exists: {expand_path(creates)})")
        return
    
    if unless is not None:
        guard = _shell_argv(module, unless, sudo, dry_run=False)
        if subprocess.run(guard, cwd=workdir, check=False).returncode == 0:
            print(f"[configure] skip: {label} (unless satisfied)")
            return

    argv = _shell_argv(module, run, sudo, dry_run=False)
    print(f"[configure] run: {label}")
    
    try:
        subprocess.run(argv, cwd=workdir, check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"commands.{module}: command failed (exit {exc.returncode}): {run}")


def apply_commands(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Run every command declared by the resolved commands modules, in pipeline
    order. A command may be guarded by `creates` (skip if a path exists) or
    `unless` (skip if a shell check exits 0); an unguarded command always runs.
    `sudo = true` escalates both the command and its `unless` guard."""
    cmd_modules = [(step, module) for step, module in modules if step == "commands"]
    if not cmd_modules:
        return
    
    total = sum(len(config[s][m].get("items", [])) for s, m in cmd_modules)
    print(f"[configure] commands: {total} item(s) across {len(cmd_modules)} module(s)")
    
    for step, module in cmd_modules:
        for item in config[step][module].get("items", []):
            _apply_one_command(module, item, dry_run)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="configure.py",
        description="Apply a dotfiles profile (invoked by bootstrap.sh).",
    )
    parser.add_argument("profile", help="profile name defined in config.toml [profiles]")
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="show what each step would do without changing anything",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    home = repo_home()
    os.environ["REPO_HOME"] = str(home)  # expands $REPO_HOME
    ensure_infra_dirs()
    seed_config(home / "config.toml")
    config = load_config(CONFIG_PATH)

    modules = resolve_profile(config, args.profile)
    print(f"[configure] profile {args.profile!r}: resolved {len(modules)} module(s)")

    # Step 1
    install_packages(home, collect_packages(config, modules), args.dry_run)

    # Step 2
    apply_directories(config, modules, args.dry_run)

    # Step 3
    apply_git(config, modules, args.dry_run)
    widen_sparse_checkout(config, modules, home, args.dry_run)

    # Step 4
    apply_files(config, modules, args.dry_run)

    # Step 5
    apply_fonts(config, modules, args.dry_run)

    # Step 6
    apply_links(config, modules, args.dry_run)

    # Step 7
    apply_services(config, modules, args.dry_run)

    # Step 8
    apply_commands(config, modules, args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
